"""The invoice contract — what the platform will accept back from any model.

This is the platform's schema, not a provider's and not an ERP's. It is
deliberately **tolerant about shape and strict about meaning**:

* every field is optional, because a model that found nine of ten fields has
  done useful work and rejecting it wholesale would throw that work away;
* keys are normalised from the synonyms models actually emit
  (``invoiceNumber``, ``invoice_no``, ``vendor``, ``bill_to``), because pinning
  the prompt's exact wording into the parser makes prompt versioning a breaking
  change;
* money and dates are coerced from the forms documents actually contain
  (``"$1,234.56"``, ``"(89.00)"``, ``"31/01/2026"``);
* anything the model volunteered that the schema does not know is **kept** in
  ``additional_fields`` rather than dropped — discarded output is evidence
  nobody can review.

Arithmetic self-consistency (line items summing to the subtotal, subtotal plus
tax reaching the total) is checked and reported as **warnings**. Warnings, not
errors, and deliberately so: whether a 3-cent discrepancy blocks a posting is an
ERP's policy, and this platform does not hold ERP policy. It reports what it
found and lets the consumer decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

INVOICE_SCHEMA_VERSION = "1.0.0"

#: Absolute tolerance for money comparisons, in the invoice's own currency
#: units. Two cents absorbs per-line rounding without hiding a real error.
_MONEY_TOLERANCE = 0.02

#: Relative tolerance, for invoices large enough that per-line rounding exceeds
#: the absolute one.
_MONEY_TOLERANCE_RATIO = 0.005

_CURRENCY_SYMBOLS = {
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
    "₩": "KRW",
    "₽": "RUB",
}

#: Everything a money string may carry that is not the number.
_MONEY_NOISE = re.compile(r"[^\d,.\-()]")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

#: Formats seen on real documents, most specific first. ISO is tried by regex
#: before this list, so these are the ambiguous human ones.
_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%m/%d/%Y", "%m-%d-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%Y/%m/%d", "%Y.%m.%d",
    "%d/%m/%y", "%m/%d/%y",
)


def _coerce_money(value: Any) -> float | None:
    """``"$1,234.56"`` → ``1234.56``; ``"(89.00)"`` → ``-89.0``; junk → ``None``.

    Returning ``None`` rather than raising is the point: a model that wrote
    ``"see attached"`` in a total field has told us something true — that it did
    not find a total — and turning that into a validation failure would discard
    every other field it got right.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")
    cleaned = _MONEY_NOISE.sub("", text).replace("(", "").replace(")", "")
    if not cleaned or cleaned in {"-", ".", ","}:
        return None

    # Decide which separator is decimal: the *last* one, when it leaves 1-2
    # digits behind it. "1.234,56" → comma decimal; "1,234.56" → dot decimal.
    last_dot, last_comma = cleaned.rfind("."), cleaned.rfind(",")
    if last_dot > last_comma:
        cleaned = cleaned.replace(",", "")
    elif last_comma > last_dot:
        tail = cleaned[last_comma + 1 :]
        cleaned = (
            cleaned[:last_comma].replace(".", "").replace(",", "") + "." + tail
            if len(tail) in (1, 2)
            else cleaned.replace(",", "").replace(".", "")
        )
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -abs(number) if negative else number


def _coerce_date(value: Any) -> str | None:
    """Normalise to ``YYYY-MM-DD`` when the form is recognisable; else keep the
    model's own text.

    Keeping unrecognised text is deliberate. A date this parser cannot read is
    still the date printed on the document, and replacing it with ``None``
    would be the platform deciding that what it cannot parse did not exist.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        return None

    iso = _ISO_DATE.match(text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return text

    normalised = text.replace(",", ", ").replace("  ", " ").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(normalised, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict | list):
        # A model that answered an address as {"line1": …, "city": …} said
        # something useful in the wrong shape. Flatten rather than discard.
        parts = (
            [f"{k}: {v}" for k, v in value.items() if v not in (None, "")]
            if isinstance(value, dict)
            else [str(v) for v in value if v not in (None, "")]
        )
        return ", ".join(parts) or None
    text = str(value).strip()
    return text or None


def _flatten_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _rename(
    payload: dict[str, Any], synonyms: dict[str, str], fields: dict[str, str] | None = None
) -> dict[str, Any]:
    """Map the model's keys onto canonical ones, case- and separator-insensitively.

    Two sources of truth, in order: the synonym table, then the model's own
    field names flattened the same way — so ``invoiceNumber``, ``Invoice
    Number`` and ``invoice-number`` all reach ``invoice_number`` without any of
    them being listed anywhere.

    A canonical key already carrying a value always wins: a model that emitted
    both ``invoice_number`` and ``invoiceNo`` is not overruled by alias
    resolution.
    """
    out: dict[str, Any] = {}
    for key, value in payload.items():
        flat = _flatten_key(key)
        canonical = synonyms.get(flat) or (fields or {}).get(flat) or str(key)
        if canonical in out and out[canonical] not in (None, "", [], {}):
            continue
        out[canonical] = value
    return out


def _flat_fields(model: type[BaseModel]) -> dict[str, str]:
    """``{"invoicenumber": "invoice_number", …}`` for one model."""
    return {_flatten_key(name): name for name in model.model_fields}


#: Synonym tables live at module scope rather than on the models: an
#: underscore-prefixed class attribute on a pydantic ``BaseModel`` becomes a
#: *private attribute*, and a validator reaching for it would get a descriptor
#: instead of a dict.
_PARTY_SYNONYMS = {
    "companyname": "name", "vendorname": "name", "suppliername": "name",
    "customername": "name", "billtoname": "name", "company": "name",
    "billingaddress": "address", "streetaddress": "address", "fulladdress": "address",
    "addressline": "address", "postaladdress": "address",
    "taxnumber": "tax_id", "vatnumber": "tax_id", "vatid": "tax_id",
    "gstnumber": "tax_id", "gstin": "tax_id", "taxregistrationnumber": "tax_id",
    "uen": "registration_number", "companyregistrationnumber": "registration_number",
    "registrationno": "registration_number", "regno": "registration_number",
    "emailaddress": "email", "contactemail": "email",
    "phonenumber": "phone", "telephone": "phone", "tel": "phone", "contactnumber": "phone",
}


class InvoiceParty(BaseModel):
    """A supplier or a customer, as printed on the document."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    address: str | None = None
    tax_id: str | None = None
    registration_number: str | None = None
    email: str | None = None
    phone: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value.strip() or None}
        if not isinstance(value, dict):
            return {}
        return _rename(value, _PARTY_SYNONYMS, _flat_fields(cls))

    @field_validator("*", mode="before")
    @classmethod
    def _strings(cls, value: Any) -> Any:
        return _coerce_str(value)

    @property
    def is_empty(self) -> bool:
        return not any(self.model_dump().values())


_LINE_ITEM_SYNONYMS = {
    "lineno": "line_number", "line": "line_number", "no": "line_number",
    "srno": "line_number", "itemnumber": "line_number", "position": "line_number",
    "item": "description", "itemdescription": "description", "desc": "description",
    "productname": "description", "particulars": "description", "details": "description",
    "sku": "product_code", "itemcode": "product_code", "productcode": "product_code",
    "partnumber": "product_code", "code": "product_code",
    "qty": "quantity", "quantities": "quantity", "units": "quantity",
    "uom": "unit", "unitofmeasure": "unit",
    "price": "unit_price", "rate": "unit_price", "unitcost": "unit_price",
    "priceperunit": "unit_price", "unitrate": "unit_price",
    "discountamount": "discount", "discountvalue": "discount",
    "taxpercent": "tax_rate", "vatrate": "tax_rate", "gstrate": "tax_rate",
    "taxvalue": "tax_amount", "vatamount": "tax_amount", "gstamount": "tax_amount",
    "total": "amount", "linetotal": "amount", "lineamount": "amount",
    "totalamount": "amount", "netamount": "amount", "value": "amount",
}


class InvoiceLineItem(BaseModel):
    """One billed line. Quantities and money are coerced; text is kept as printed."""

    model_config = ConfigDict(extra="ignore")

    line_number: int | None = None
    description: str | None = None
    product_code: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    discount: float | None = None
    tax_rate: float | None = None
    tax_amount: float | None = None
    amount: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"description": value.strip() or None}
        if not isinstance(value, dict):
            return {}
        return _rename(value, _LINE_ITEM_SYNONYMS, _flat_fields(cls))

    @field_validator(
        "quantity", "unit_price", "discount", "tax_rate", "tax_amount", "amount",
        mode="before",
    )
    @classmethod
    def _money(cls, value: Any) -> Any:
        return _coerce_money(value)

    @field_validator("line_number", mode="before")
    @classmethod
    def _line_number(cls, value: Any) -> Any:
        number = _coerce_money(value)
        return int(number) if number is not None else None

    @field_validator("description", "product_code", "unit", mode="before")
    @classmethod
    def _strings(cls, value: Any) -> Any:
        return _coerce_str(value)

    @property
    def is_empty(self) -> bool:
        return not any(self.model_dump().values())

    @property
    def computed_amount(self) -> float | None:
        if self.quantity is None or self.unit_price is None:
            return None
        return round(self.quantity * self.unit_price, 2)


_TOTALS_SYNONYMS = {
    "netamount": "subtotal", "nettotal": "subtotal", "subtotalamount": "subtotal",
    "amountbeforetax": "subtotal", "totalexcludingtax": "subtotal", "totalexcltax": "subtotal",
    "discount": "discount_total", "totaldiscount": "discount_total",
    "tax": "tax_total", "totaltax": "tax_total", "vat": "tax_total",
    "vattotal": "tax_total", "gst": "tax_total", "gsttotal": "tax_total",
    "salestax": "tax_total", "taxamount": "tax_total",
    "shipping": "shipping_total", "freight": "shipping_total",
    "deliverycharge": "shipping_total", "shippingcharges": "shipping_total",
    "total": "grand_total", "totalamount": "grand_total", "invoicetotal": "grand_total",
    "grandtotal": "grand_total", "totalincludingtax": "grand_total",
    "totalincltax": "grand_total", "amountpayable": "grand_total",
    "paid": "amount_paid", "amountreceived": "amount_paid", "totalpaid": "amount_paid",
    "balancedue": "amount_due", "amountoutstanding": "amount_due",
    "duenow": "amount_due", "balance": "amount_due",
}


class InvoiceTotals(BaseModel):
    """The money summary. Every figure optional, every figure coerced."""

    model_config = ConfigDict(extra="ignore")

    subtotal: float | None = None
    discount_total: float | None = None
    tax_total: float | None = None
    shipping_total: float | None = None
    grand_total: float | None = None
    amount_paid: float | None = None
    amount_due: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if isinstance(value, int | float):
            return {"grand_total": float(value)}
        if not isinstance(value, dict):
            return {}
        return _rename(value, _TOTALS_SYNONYMS, _flat_fields(cls))

    @field_validator("*", mode="before")
    @classmethod
    def _money(cls, value: Any) -> Any:
        return _coerce_money(value)

    @property
    def is_empty(self) -> bool:
        return not any(v is not None for v in self.model_dump().values())


_INVOICE_SYNONYMS = {
    "type": "document_type", "documenttype": "document_type", "doctype": "document_type",
    "invoiceno": "invoice_number", "invoicenumber": "invoice_number",
    "invoiceid": "invoice_number", "billnumber": "invoice_number",
    "documentnumber": "invoice_number", "number": "invoice_number",
    "invoicenum": "invoice_number", "referencenumber": "invoice_number",
    "ponumber": "purchase_order_number", "purchaseorder": "purchase_order_number",
    "purchaseorderno": "purchase_order_number", "po": "purchase_order_number",
    "date": "invoice_date", "invoicedate": "invoice_date",
    "issuedate": "invoice_date", "billdate": "invoice_date", "dateissued": "invoice_date",
    "duedate": "due_date", "paymentduedate": "due_date", "datedue": "due_date",
    "currencycode": "currency", "currencies": "currency",
    "vendor": "supplier", "seller": "supplier", "from": "supplier",
    "supplierdetails": "supplier", "vendordetails": "supplier", "billfrom": "supplier",
    "issuer": "supplier", "company": "supplier",
    "buyer": "customer", "billto": "customer", "customerdetails": "customer",
    "soldto": "customer", "client": "customer", "recipient": "customer", "to": "customer",
    "lineitems": "line_items", "items": "line_items", "lines": "line_items",
    "products": "line_items", "invoicelines": "line_items", "details": "line_items",
    "summary": "totals", "amounts": "totals",
    "paymentterms": "payment_terms", "terms": "payment_terms",
    "termsofpayment": "payment_terms",
    "paymentreference": "payment_reference", "reference": "payment_reference",
    "bankdetails": "bank_details", "bankinformation": "bank_details",
    "paymentdetails": "bank_details", "remittanceinformation": "bank_details",
    "note": "notes", "comments": "notes", "remarks": "notes", "memo": "notes",
}

_INVOICE_KNOWN_FIELDS = frozenset(
    {
        "document_type", "invoice_number", "purchase_order_number", "invoice_date",
        "due_date", "currency", "supplier", "customer", "line_items", "totals",
        "payment_terms", "payment_reference", "bank_details", "notes",
        "additional_fields",
    }
)


class InvoiceDocument(BaseModel):
    """The platform's invoice. Provider-neutral, ERP-neutral, prompt-neutral."""

    model_config = ConfigDict(extra="ignore")

    document_type: str = "invoice"
    invoice_number: str | None = None
    purchase_order_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    supplier: InvoiceParty = Field(default_factory=InvoiceParty)
    customer: InvoiceParty = Field(default_factory=InvoiceParty)
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    totals: InvoiceTotals = Field(default_factory=InvoiceTotals)
    payment_terms: str | None = None
    payment_reference: str | None = None
    bank_details: str | None = None
    notes: str | None = None
    additional_fields: dict[str, Any] = Field(default_factory=dict)
    """Everything the model volunteered that this schema does not name. Kept
    because a discarded field is a field nobody can review, and the next version
    of this schema is written from exactly these."""

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return {}
        # Models sometimes wrap the answer: {"invoice": {...}} / {"data": {...}}.
        for wrapper in ("invoice", "data", "result", "extraction", "document"):
            inner = value.get(wrapper)
            if isinstance(inner, dict) and len(value) <= 2:
                value = {**{k: v for k, v in value.items() if k != wrapper}, **inner}
                break

        renamed = _rename(value, _INVOICE_SYNONYMS, _flat_fields(cls))
        extras = {k: v for k, v in renamed.items() if k not in _INVOICE_KNOWN_FIELDS}
        known = {k: v for k, v in renamed.items() if k in _INVOICE_KNOWN_FIELDS}

        volunteered = known.get("additional_fields")
        merged = dict(volunteered) if isinstance(volunteered, dict) else {}
        merged.update(extras)
        if merged:
            known["additional_fields"] = merged

        items = known.get("line_items")
        if isinstance(items, dict):
            # A single line item emitted unwrapped, or keyed by index.
            values = list(items.values())
            known["line_items"] = values if all(isinstance(v, dict) for v in values) else [items]
        elif items is not None and not isinstance(items, list):
            known["line_items"] = []
        return known

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def _dates(cls, value: Any) -> Any:
        return _coerce_date(value)

    @field_validator(
        "invoice_number", "purchase_order_number", "payment_terms",
        "payment_reference", "bank_details", "notes",
        mode="before",
    )
    @classmethod
    def _strings(cls, value: Any) -> Any:
        return _coerce_str(value)

    @field_validator("document_type", mode="before")
    @classmethod
    def _document_type(cls, value: Any) -> Any:
        return _coerce_str(value) or "invoice"

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: Any) -> Any:
        text = _coerce_str(value)
        if not text:
            return None
        if text in _CURRENCY_SYMBOLS:
            return _CURRENCY_SYMBOLS[text]
        stripped = text.strip().upper()
        return stripped if re.fullmatch(r"[A-Z]{3}", stripped) else text

    @field_validator("line_items")
    @classmethod
    def _drop_empty_items(cls, items: list[InvoiceLineItem]) -> list[InvoiceLineItem]:
        """A model padding to a round number emits empty objects. They are not
        line items, and keeping them would inflate every count downstream."""
        return [item for item in items if not item.is_empty]

    @property
    def is_empty(self) -> bool:
        """Nothing was extracted. Distinct from "an invoice with few fields"."""
        return not any(
            (
                self.invoice_number,
                self.purchase_order_number,
                self.invoice_date,
                self.due_date,
                self.line_items,
                not self.totals.is_empty,
                not self.supplier.is_empty,
                not self.customer.is_empty,
            )
        )


# ── validation ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class InvoiceValidationResult:
    """The verdict, with its reasons. Never an exception — the caller decides.

    ``errors`` mean the payload is not an invoice this platform can return.
    ``warnings`` mean it is, but something about it deserves a human's attention
    before an ERP posts it.
    """

    valid: bool
    invoice: InvoiceDocument | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    schema_version: str = INVOICE_SCHEMA_VERSION

    @property
    def data(self) -> dict[str, Any]:
        return self.invoice.model_dump() if self.invoice is not None else {}


def _close_enough(left: float, right: float) -> bool:
    tolerance = max(_MONEY_TOLERANCE, abs(right) * _MONEY_TOLERANCE_RATIO)
    return abs(left - right) <= tolerance


class InvoiceSchemaValidator:
    """Validates model output against the invoice schema. Never raises.

    Consistency checks are *arithmetic*, not commercial: they verify the
    document adds up, which is a property of the document. Whether a mismatch
    blocks payment is an ERP decision, and this class does not make it.
    """

    schema_version = INVOICE_SCHEMA_VERSION

    def validate(self, payload: Any) -> InvoiceValidationResult:
        if not isinstance(payload, dict):
            return InvoiceValidationResult(
                valid=False,
                errors=(
                    f"model returned {type(payload).__name__}, not a JSON object; "
                    f"an invoice extraction must be an object",
                ),
            )

        try:
            invoice = InvoiceDocument.model_validate(payload)
        except ValidationError as exc:
            return InvoiceValidationResult(
                valid=False,
                errors=tuple(
                    f"{'.'.join(str(p) for p in err['loc']) or 'document'}: {err['msg']}"
                    for err in exc.errors()[:20]
                ),
            )

        if invoice.is_empty:
            return InvoiceValidationResult(
                valid=False,
                invoice=invoice,
                errors=(
                    "no invoice fields were extracted; the document may not be an "
                    "invoice, or may not be legible",
                ),
            )

        return InvoiceValidationResult(
            valid=True, invoice=invoice, warnings=tuple(self._warnings(invoice))
        )

    def _warnings(self, invoice: InvoiceDocument) -> list[str]:
        found: list[str] = []

        for label, value in (
            ("invoice_number", invoice.invoice_number),
            ("invoice_date", invoice.invoice_date),
            ("currency", invoice.currency),
            ("supplier.name", invoice.supplier.name),
            ("totals.grand_total", invoice.totals.grand_total),
        ):
            if value in (None, ""):
                found.append(f"missing expected field: {label}")

        if not invoice.line_items:
            found.append("no line items were extracted")

        totals = invoice.totals
        line_sum = sum(item.amount for item in invoice.line_items if item.amount is not None)
        if invoice.line_items and totals.subtotal is not None and line_sum:
            if not _close_enough(line_sum, totals.subtotal):
                found.append(
                    f"line items sum to {line_sum:.2f} but subtotal is {totals.subtotal:.2f}"
                )

        if totals.subtotal is not None and totals.grand_total is not None:
            expected = (
                totals.subtotal
                + (totals.tax_total or 0.0)
                + (totals.shipping_total or 0.0)
                - (totals.discount_total or 0.0)
            )
            if not _close_enough(expected, totals.grand_total):
                found.append(
                    f"subtotal plus tax and charges is {expected:.2f} but grand total "
                    f"is {totals.grand_total:.2f}"
                )

        if totals.grand_total is not None and totals.amount_due is not None:
            expected_due = totals.grand_total - (totals.amount_paid or 0.0)
            if not _close_enough(expected_due, totals.amount_due):
                found.append(
                    f"grand total less payments is {expected_due:.2f} but amount due "
                    f"is {totals.amount_due:.2f}"
                )

        for index, item in enumerate(invoice.line_items, start=1):
            computed = item.computed_amount
            if computed is not None and item.amount is not None:
                if not _close_enough(computed, item.amount):
                    found.append(
                        f"line {index}: quantity times unit price is {computed:.2f} but "
                        f"amount is {item.amount:.2f}"
                    )

        if invoice.invoice_date and invoice.due_date:
            try:
                if date.fromisoformat(invoice.due_date) < date.fromisoformat(
                    invoice.invoice_date
                ):
                    found.append("due date precedes invoice date")
            except ValueError:
                pass  # unparsed dates are already preserved verbatim; not an error

        return found

    @staticmethod
    def json_schema() -> dict[str, Any]:
        """The schema as JSON Schema — for prompts and for constrained decoding.

        Generated from the model rather than hand-written, so a field added to
        ``InvoiceDocument`` cannot drift from the shape the model is asked for.
        """
        return InvoiceDocument.model_json_schema()


__all__ = [
    "INVOICE_SCHEMA_VERSION",
    "InvoiceDocument",
    "InvoiceLineItem",
    "InvoiceParty",
    "InvoiceSchemaValidator",
    "InvoiceTotals",
    "InvoiceValidationResult",
]
