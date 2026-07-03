"""
Business domain prompt modules.
"""

from __future__ import annotations

BUSINESS_GENERAL = """\
Business systems expertise: you understand business operations, workflows, \
KPIs, ROI analysis, process optimization, and change management. \
You translate technical solutions into business value."""

HOTEL_MANAGEMENT = """\
Hotel Management System expertise:
- PMS (Property Management System): reservations, check-in/check-out, room management
- Revenue Management: RevPAR, ADR, occupancy rate, dynamic pricing
- F&B Management: restaurant POS, banquet management, room service
- Housekeeping: room status workflow (dirty→clean→inspected→available)
- OTA Integration: Booking.com, Expedia, Airbnb channel management
- Front Desk Operations: walk-ins, group bookings, corporate accounts
- Reporting: daily revenue reports, occupancy forecasts, guest history"""

ERP = """\
ERP System expertise:
- Finance Module: GL, AP, AR, bank reconciliation, financial reporting
- Procurement: purchase requisition → PO → GRN → invoice matching (3-way match)
- Inventory: stock valuation (FIFO/LIFO/weighted average), reorder points
- HR/Payroll: employee master, attendance, leave management, payroll processing
- Manufacturing: BOM, work orders, production planning, MRP
- Reporting: P&L, balance sheet, cash flow, management dashboards"""

POS = """\
Point of Sale System expertise:
- Transaction Processing: item scanning, discounts, tax calculation, payment methods
- Inventory Sync: real-time stock deduction, low-stock alerts, reorder triggers
- Payment Integration: cash, card (PCI-DSS compliance), UPI, digital wallets
- Loyalty Programs: points accumulation, redemption, tier management
- Reporting: sales by item/category/cashier, hourly trends, end-of-day reconciliation
- Offline Mode: local transaction queue with sync on reconnect"""

INVENTORY = """\
Inventory Management expertise:
- Stock Control: SKU management, batch/lot tracking, expiry management
- Warehouse Operations: bin locations, pick-pack-ship, cycle counting
- Demand Forecasting: moving average, seasonal adjustments, safety stock
- Supplier Management: lead times, MOQ, vendor scorecards
- Valuation: FIFO, LIFO, weighted average cost methods
- Reporting: stock aging, slow-moving items, ABC analysis"""

FINANCE = """\
Finance System expertise:
- Chart of Accounts: asset, liability, equity, revenue, expense classification
- Journal Entries: double-entry bookkeeping, accruals, deferrals
- Reconciliation: bank reconciliation, inter-company reconciliation
- Financial Reporting: IFRS/GAAP compliance, consolidated statements
- Budgeting: budget vs actual variance analysis, rolling forecasts
- Audit Trail: every financial transaction must be immutable and traceable"""

CRM = """\
CRM System expertise:
- Lead Management: lead scoring, pipeline stages, conversion tracking
- Customer 360: interaction history, purchase history, support tickets
- Sales Automation: follow-up reminders, email sequences, deal tracking
- Analytics: win rate, average deal size, sales cycle length, churn prediction
- Integration: email, calendar, telephony, marketing automation"""

HRMS = """\
HRMS expertise:
- Employee Lifecycle: onboarding, transfers, promotions, offboarding
- Attendance & Leave: biometric integration, leave policies, approval workflows
- Payroll: gross-to-net calculation, statutory deductions, payslip generation
- Performance: goal setting, appraisal cycles, 360-degree feedback
- Compliance: labor law adherence, statutory reporting (PF, ESI, TDS)"""
