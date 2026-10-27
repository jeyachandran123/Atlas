"""The invoice schema: tolerant about shape, strict about meaning.

Two failure modes are being guarded against at once. Rejecting a good
extraction because a model wrote ``invoiceNumber`` instead of
``invoice_number`` throws away work that was paid for. Accepting an empty
object as an invoice puts a document nobody read into an ERP. The tests below
pull in both directions on purpose.
"""

from __future__ import annotations

import pytest

from app.document_platform.vlm.invoice_schema import (
    INVOICE_SCHEMA_VERSION,
    InvoiceDocument,
    InvoiceSchemaValidator,
)

from .conftest import VALID_INVOICE_JSON


@pytest.fixture
def validator() -> InvoiceSchemaValidator:
    return InvoiceSchemaValidator()


class TestHappyPath:
    def test_a_well_formed_invoice_validates_without_warnings(self, validator) -> None:
        from datetime import date, timedelta

        # Dated relative to today: the date-plausibility check flags a fixed
        # fixture date once it is more than a year old.
        issued = date.today() - timedelta(days=5)
        current = {
            **VALID_INVOICE_JSON,
            "invoice_date": issued.isoformat(),
            "due_date": (issued + timedelta(days=30)).isoformat(),
        }
        result = validator.validate(current)
        assert result.valid
        assert result.errors == ()
        assert result.warnings == (), result.warnings
        assert result.schema_version == INVOICE_SCHEMA_VERSION

    def test_the_data_is_normalised_and_complete(self, validator) -> None:
        data = validator.validate(VALID_INVOICE_JSON).data
        assert data["invoice_number"] == "INV-2026-0042"
        assert data["currency"] == "SGD"
        assert len(data["line_items"]) == 2
        assert data["totals"]["grand_total"] == 305.2


class TestKeyNormalisation:
    @pytest.mark.parametrize(
        "key",
        ["invoice_number", "invoiceNumber", "Invoice Number", "invoice-no", "billNumber"],
    )
    def test_invoice_number_synonyms_all_land_on_one_field(self, validator, key) -> None:
        result = validator.validate({key: "INV-7"})
        assert result.valid
        assert result.data["invoice_number"] == "INV-7"

    def test_party_synonyms_are_resolved(self, validator) -> None:
        data = validator.validate(
            {"vendor": {"companyName": "Acme"}, "billTo": {"name": "FBH"}}
        ).data
        assert data["supplier"]["name"] == "Acme"
        assert data["customer"]["name"] == "FBH"

    def test_a_party_given_as_a_bare_string_becomes_a_name(self, validator) -> None:
        data = validator.validate({"supplier": "Acme Pte Ltd"}).data
        assert data["supplier"]["name"] == "Acme Pte Ltd"

    def test_a_party_address_object_is_flattened_rather_than_dropped(self, validator) -> None:
        data = validator.validate(
            {"supplier": {"name": "Acme", "address": {"line1": "1 Main St", "city": "SG"}}}
        ).data
        assert "1 Main St" in data["supplier"]["address"]

    def test_a_wrapped_answer_is_unwrapped(self, validator) -> None:
        """Models wrap the object in ``{"invoice": …}`` often enough that
        refusing it would fail extractions over punctuation."""
        data = validator.validate({"invoice": {"invoice_number": "INV-9"}}).data
        assert data["invoice_number"] == "INV-9"

    def test_unknown_fields_are_kept_not_discarded(self, validator) -> None:
        data = validator.validate(
            {"invoice_number": "INV-1", "shipping_tracking_no": "SG123"}
        ).data
        assert data["additional_fields"]["shipping_tracking_no"] == "SG123"

    def test_a_canonical_key_wins_over_a_synonym(self, validator) -> None:
        data = validator.validate({"invoice_number": "REAL", "billNumber": "ALIAS"}).data
        assert data["invoice_number"] == "REAL"


class TestCoercion:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1234.56", 1234.56),
            ("$1,234.56", 1234.56),
            ("SGD 1,234.56", 1234.56),
            ("1.234,56", 1234.56),
            ("(89.00)", -89.0),
            (1234.56, 1234.56),
            ("", None),
            ("see attached", None),
        ],
    )
    def test_money_is_read_the_way_documents_write_it(self, validator, raw, expected) -> None:
        data = validator.validate({"invoice_number": "X", "totals": {"total": raw}}).data
        assert data["totals"]["grand_total"] == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-01-15", "2026-01-15"),
            ("15/01/2026", "2026-01-15"),
            ("15 Jan 2026", "2026-01-15"),
            ("January 15, 2026", "2026-01-15"),
        ],
    )
    def test_dates_normalise_to_iso(self, validator, raw, expected) -> None:
        data = validator.validate({"invoice_date": raw}).data
        assert data["invoice_date"] == expected

    def test_an_unparseable_date_is_preserved_rather_than_nulled(self, validator) -> None:
        """What this parser cannot read is still printed on the document."""
        data = validator.validate({"invoice_date": "the 3rd of never"}).data
        assert data["invoice_date"] == "the 3rd of never"

    @pytest.mark.parametrize(
        ("raw", "expected"), [("sgd", "SGD"), ("€", "EUR"), ("USD", "USD"), ("dollars", "dollars")]
    )
    def test_currency_normalises_only_when_unambiguous(self, validator, raw, expected) -> None:
        data = validator.validate({"invoice_number": "X", "currency": raw}).data
        assert data["currency"] == expected

    def test_a_totals_number_given_bare_becomes_the_grand_total(self, validator) -> None:
        data = validator.validate({"invoice_number": "X", "totals": 500}).data
        assert data["totals"]["grand_total"] == 500.0

    def test_empty_line_items_are_dropped(self, validator) -> None:
        data = validator.validate(
            {"invoice_number": "X", "line_items": [{"description": "Real"}, {}, {}]}
        ).data
        assert len(data["line_items"]) == 1


class TestRejection:
    def test_a_non_object_is_rejected(self, validator) -> None:
        result = validator.validate([1, 2, 3])
        assert not result.valid and "not a JSON object" in result.errors[0]

    def test_an_empty_object_is_rejected_rather_than_returned_as_an_invoice(
        self, validator
    ) -> None:
        """The dangerous case: a model that found nothing and said so in JSON.
        Returning that as a valid invoice puts an unread document into an ERP."""
        result = validator.validate({})
        assert not result.valid
        assert "no invoice fields" in result.errors[0]

    def test_an_all_null_invoice_is_rejected(self, validator) -> None:
        result = validator.validate(
            {"invoice_number": None, "invoice_date": None, "line_items": []}
        )
        assert not result.valid

    def test_null_line_items_are_an_empty_list_not_a_schema_error(self, validator) -> None:
        """The prompt's example shape invites ``"line_items": null``."""
        result = validator.validate({"invoice_number": "X", "line_items": None})
        assert result.valid
        assert result.data["line_items"] == []

    def test_validation_never_raises(self, validator) -> None:
        for payload in (None, "text", 42, [], {"line_items": "not a list"}):
            assert validator.validate(payload) is not None


class TestConsistencyWarnings:
    def test_line_items_that_do_not_sum_to_the_subtotal_warn(self, validator) -> None:
        result = validator.validate(
            {
                **VALID_INVOICE_JSON,
                "line_items": [{"description": "A", "amount": 100.0}],
                "totals": {"subtotal": 280.0, "tax_total": 25.2, "grand_total": 305.2},
            }
        )
        assert result.valid, "an arithmetic mismatch is a warning, never a rejection"
        assert any("line items sum" in w for w in result.warnings)

    def test_a_total_that_does_not_add_up_warns(self, validator) -> None:
        result = validator.validate(
            {**VALID_INVOICE_JSON, "totals": {"subtotal": 280.0, "tax_total": 25.2, "grand_total": 999.0}}
        )
        assert any("grand total" in w for w in result.warnings)

    def test_rounding_within_tolerance_does_not_warn(self, validator) -> None:
        result = validator.validate(
            {**VALID_INVOICE_JSON, "totals": {"subtotal": 280.0, "tax_total": 25.2, "grand_total": 305.21}}
        )
        assert not any("grand total" in w for w in result.warnings)

    def test_a_line_whose_quantity_times_price_disagrees_warns(self, validator) -> None:
        result = validator.validate(
            {
                "invoice_number": "X",
                "line_items": [{"description": "A", "quantity": 2, "unit_price": 10.0, "amount": 50.0}],
            }
        )
        assert any("quantity times unit price" in w for w in result.warnings)

    def test_missing_expected_fields_warn_without_failing(self, validator) -> None:
        result = validator.validate({"invoice_number": "INV-1"})
        assert result.valid
        assert any("missing expected field: currency" in w for w in result.warnings)
        assert any("no line items" in w for w in result.warnings)

    def test_a_due_date_before_the_invoice_date_warns(self, validator) -> None:
        result = validator.validate(
            {"invoice_number": "X", "invoice_date": "2026-02-01", "due_date": "2026-01-01"}
        )
        assert any("due date precedes" in w for w in result.warnings)


class TestSchemaExport:
    def test_the_json_schema_is_generated_from_the_model(self) -> None:
        schema = InvoiceSchemaValidator.json_schema()
        assert schema["type"] == "object"
        assert "invoice_number" in schema["properties"]

    def test_the_schema_and_the_model_cannot_drift(self) -> None:
        schema = InvoiceSchemaValidator.json_schema()
        assert set(InvoiceDocument.model_fields) <= set(schema["properties"])


class TestMultipleInvoices:
    """One upload, several invoices — a scanned page of petty-cash receipts."""

    def test_the_envelope_yields_one_entry_per_invoice_in_order(self, validator) -> None:
        result = validator.validate_many(
            {
                "invoices": [
                    {"invoice_number": "T02067275", "totals": {"grand_total": 28.40}},
                    {"invoice_number": "091026/10027/14/00164", "totals": {"grand_total": 90.40}},
                    {"invoice_number": "161026/10027/07/00059", "totals": {"grand_total": 21.00}},
                    {"invoice_number": "131026/10027/15/00068", "totals": {"grand_total": 26.00}},
                ]
            }
        )
        assert result.valid
        assert [d["invoice_number"] for d in result.data] == [
            "T02067275",
            "091026/10027/14/00164",
            "161026/10027/07/00059",
            "131026/10027/15/00068",
        ]
        assert [d["totals"]["grand_total"] for d in result.data] == [28.4, 90.4, 21.0, 26.0]

    def test_a_single_invoice_object_becomes_a_one_element_list(self, validator) -> None:
        """What prompt 1.0.0 asks for, so a pinned old version keeps working."""
        result = validator.validate_many(VALID_INVOICE_JSON)
        assert result.valid
        assert len(result.data) == 1
        assert result.data[0]["invoice_number"] == "INV-2026-0042"

    def test_each_entry_keeps_every_field_the_single_shape_has(self, validator) -> None:
        single = validator.validate(VALID_INVOICE_JSON).data
        many = validator.validate_many({"invoices": [VALID_INVOICE_JSON]}).data
        assert many == [single]

    def test_warnings_name_the_invoice_they_belong_to(self, validator) -> None:
        result = validator.validate_many(
            {"invoices": [VALID_INVOICE_JSON, {"invoice_number": "INV-2"}]}
        )
        assert any(w.startswith("invoice 2: missing expected field") for w in result.warnings)
        assert not any(w.startswith("invoice 1: missing expected field") for w in result.warnings)

    def test_an_empty_entry_beside_real_ones_is_omitted_and_reported(self, validator) -> None:
        result = validator.validate_many({"invoices": [VALID_INVOICE_JSON, {}]})
        assert result.valid
        assert len(result.data) == 1
        assert any("omitted" in w and "invoice 2" in w for w in result.warnings)

    def test_no_valid_entry_is_rejected(self, validator) -> None:
        result = validator.validate_many({"invoices": [{}, {"line_items": []}]})
        assert not result.valid
        assert result.errors[0].startswith("invoice 1: no invoice fields")

    def test_an_empty_list_is_rejected(self, validator) -> None:
        result = validator.validate_many({"invoices": []})
        assert not result.valid
        assert "empty invoice list" in result.errors[0]

    def test_a_non_object_is_rejected(self, validator) -> None:
        result = validator.validate_many([VALID_INVOICE_JSON])
        assert not result.valid and "not a JSON object" in result.errors[0]

    def test_the_batch_schema_wraps_the_invoice_schema(self) -> None:
        schema = InvoiceSchemaValidator.batch_json_schema()
        assert schema["properties"]["invoices"]["type"] == "array"


class TestReceiptTotals:
    """Receipts print a total and no subtotal; a misread total must still warn."""

    @staticmethod
    def _receipt(total: float) -> dict:
        return {
            "invoice_number": "R-1",
            "line_items": [{"description": "a", "amount": 5.20}, {"description": "b", "amount": 15.60}],
            "totals": {"grand_total": total},
        }

    def test_a_total_that_disagrees_with_its_lines_warns(self, validator) -> None:
        result = validator.validate(self._receipt(20.0))
        assert result.valid
        assert any("grand total is 20.00" in w for w in result.warnings)

    def test_a_total_that_matches_its_lines_does_not_warn(self, validator) -> None:
        result = validator.validate(self._receipt(20.80))
        assert not any("grand total" in w for w in result.warnings)

    def test_cash_rounding_is_within_tolerance(self, validator) -> None:
        result = validator.validate(self._receipt(20.79))
        assert not any("grand total" in w for w in result.warnings)


class TestDatePlausibility:
    """A misread year is a valid-looking date; it must be flagged, not trusted."""

    def test_a_date_more_than_a_year_old_warns(self, validator) -> None:
        from datetime import date, timedelta

        old = (date.today() - timedelta(days=400)).isoformat()
        result = validator.validate({"invoice_number": "X", "invoice_date": old})
        assert result.valid
        assert any("more than a year old" in w for w in result.warnings)

    def test_a_future_date_warns(self, validator) -> None:
        from datetime import date, timedelta

        future = (date.today() + timedelta(days=30)).isoformat()
        result = validator.validate({"invoice_number": "X", "invoice_date": future})
        assert any("in the future" in w for w in result.warnings)

    def test_a_recent_date_does_not_warn(self, validator) -> None:
        from datetime import date, timedelta

        recent = (date.today() - timedelta(days=5)).isoformat()
        result = validator.validate({"invoice_number": "X", "invoice_date": recent})
        assert not any("check the year" in w for w in result.warnings)
