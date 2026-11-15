# StockWise AI
## Product Requirements Document (PRD) — MVP v1.0

**Project duration:** 4 weeks
**Initial market:** Lesotho, with broader African SME applicability
**Primary objective:** Build a competition-ready AI-assisted inventory and procurement management product.

---

## 1. Product overview

StockWise AI is an intelligent inventory management and procurement assistant designed to help small and medium-sized businesses make better stock decisions.

It combines conventional inventory management with deterministic reorder calculations and an AI assistant that explains inventory conditions and recommendations using actual business data.

The product must help business owners and staff answer:

- What stock do we currently have?
- Which products are running low?
- Which products are at risk of running out?
- What quantities should we reorder?
- What should we purchase first?
- Why is a particular purchase being recommended?

StockWise AI must not invent inventory figures, sales history, supplier details or purchasing facts.

## 2. Problem statement

Many small businesses manage inventory using spreadsheets, notebooks or disconnected systems. This makes it difficult to identify low-stock products, estimate future demand, maintain appropriate safety stock and plan purchases.

Consequences include:
- Lost sales because products run out.
- Excess capital tied up in slow-moving stock.
- Emergency purchasing and avoidable procurement costs.
- Poor visibility into inventory performance.
- Decisions based on incomplete or outdated information.

StockWise AI aims to improve inventory visibility and provide understandable, evidence-based purchasing recommendations.

## 3. Target users

### Primary users
1. Retail shop owners and managers.
2. Wholesalers and distributors.
3. Hardware store owners and inventory managers.

### User roles for MVP
- **Business owner/admin:** Manages products, inventory, sales records and purchasing decisions.
- **Staff/operator:** Views inventory, records stock movements and reviews recommendations.

For the first MVP, implement a simple demonstration environment. Full multi-tenant account management and sophisticated permissions are not required.

## 4. Product objectives

1. Maintain accurate product and inventory records.
2. Record stock movements with traceable history.
3. Identify products below their reorder thresholds.
4. Calculate suggested reorder quantities using transparent rules.
5. Explain recommendations in understandable language.
6. Allow users to review and approve purchase recommendations.
7. Import and export inventory information through CSV.
8. Demonstrate measurable improvements in inventory visibility and decision-making.

## 5. MVP functional requirements

### FR-01: Product management
Users must be able to:
- Add products.
- View and search products.
- Edit product details.
- Activate or deactivate products.
- Assign SKU, name, category and unit.
- Record cost price and selling price.
- Define reorder level, safety stock and supplier lead time.

Each product must have a unique SKU within the business.

### FR-02: Inventory tracking
Users must be able to:
- View current stock quantities.
- Record stock received.
- Record stock sold or issued.
- Record manual stock adjustments with a reason.
- View stock movement history.

Every stock movement must be traceable to its type, quantity, date and reference.

Stock must never become negative through a normal sale or issue operation.

### FR-03: Sales history
Users must be able to:
- Record sales transactions.
- Associate sales quantities with products.
- View historical sales records.
- Use available sales history for demand calculations.

The MVP will not integrate with an external POS system.

### FR-04: Inventory dashboard
The dashboard must show:
- Total active products.
- Total units in stock.
- Low-stock product count.
- Out-of-stock product count.
- Products requiring reorder attention.
- Recent stock movements.
- Important inventory alerts.

All figures must come from the application database.

### FR-05: Reorder recommendation engine
The application must calculate reorder recommendations using deterministic, testable Python logic.

Initial calculation rules:

**Average daily demand**

Average daily demand = Units sold during the selected historical period / Number of days in that period.

**Lead-time demand**

Lead-time demand = Average daily demand × Supplier lead time in days.

**Reorder point**

Reorder point = Lead-time demand + Safety stock.

**Suggested reorder quantity**

Suggested reorder quantity = max(0, Target stock level − Current stock).

The target stock level must account for lead-time demand and safety stock. The initial implementation should use a clearly documented, configurable coverage period.

The system must:
- Identify products at or below their reorder point.
- Explain why a product needs attention.
- Show the current stock, reorder point and suggested quantity.
- Identify insufficient sales history.
- Avoid presenting estimates as actual sales data.

### FR-06: AI inventory assistant
Users must be able to ask questions such as:
- Which products need reordering?
- Why is this product considered low stock?
- Which products have the highest inventory risk?
- Summarise the current inventory position.
- Explain the recommended purchase quantities.

The assistant must:
- Retrieve relevant information from application services.
- Use actual inventory data as its evidence.
- Clearly distinguish facts from estimates.
- State when information is unavailable.
- Avoid changing inventory or approving purchases.
- Never invent suppliers, prices, sales figures or stock quantities.

If the AI provider is unavailable, deterministic inventory functionality must continue working.

### FR-07: Purchase recommendations and approval
Users must be able to:
- Generate a draft purchase recommendation.
- Review suggested products and quantities.
- Edit a suggested quantity.
- Approve or reject the recommendation.
- View approval status and timestamps.

Approval must not automatically send orders to suppliers or make payments.

### FR-08: CSV import and export
Users must be able to:
- Import product information from a CSV file.
- Validate required columns and data types.
- Preview validation errors.
- Export product and inventory information.
- Download inventory and reorder reports.

Invalid rows must not silently corrupt existing inventory records.

## 6. Non-functional requirements

### NFR-01: Accuracy
Inventory calculations must be deterministic and covered by automated tests.

### NFR-02: Reliability
Core inventory functionality must remain available if the AI provider is unavailable.

### NFR-03: Security
- Validate all API inputs.
- Keep API keys and secrets in environment variables.
- Do not commit secrets to Git.
- Use appropriate error handling.
- Do not expose sensitive internal errors to users.

### NFR-04: Usability
The interface must be responsive, understandable and suitable for non-technical business users.

### NFR-05: Maintainability
Use modular backend services, documented API contracts and reusable frontend components.

### NFR-06: Deployment
The MVP must be runnable locally and packaged using Docker.

### NFR-07: Testability
Core business rules, API endpoints and important user workflows must have automated tests.

## 7. Proposed technical architecture

**Frontend**
- React
- Vite
- Tailwind CSS
- Recharts

**Backend**
- Python
- FastAPI
- Pydantic
- SQLAlchemy

**Database**
- SQLite for the MVP.

**AI**
- OpenAI API through a dedicated AI service.
- Structured application data supplied to the assistant through controlled backend tools.
- Deterministic fallback when AI is unavailable.

**Data processing**
- Python CSV processing; Pandas where it provides a clear benefit.

**Testing**
- Pytest for backend tests.
- Frontend tests for important interface behaviour.
- API integration tests.

**Deployment and version control**
- Docker and Docker Compose.
- Git and GitHub.

## 8. Initial data entities

- Product
- Category
- InventoryBalance
- StockMovement
- Sale
- SaleItem
- Supplier (basic optional reference data)
- PurchaseRecommendation
- PurchaseRecommendationItem
- ApprovalRecord

Use database relationships and constraints to preserve data integrity.

## 9. Explicit exclusions from MVP

To protect the one-month timeline, the following are deferred:
- Live supplier integrations.
- Automated supplier ordering.
- Payment processing.
- WhatsApp integration.
- Accounting integrations.
- External POS integrations.
- Predictive machine-learning models.
- Complex multi-tenant SaaS infrastructure.
- Advanced role-based access control.
- Native mobile applications.

These can be evaluated after the MVP.

## 10. Acceptance criteria

The MVP is considered functionally complete when:

1. A user can create, update and view products.
2. Inventory movements update stock correctly.
3. Sales reduce stock and are recorded in history.
4. The dashboard reflects actual database values.
5. Low-stock products are identified correctly.
6. Reorder calculations pass defined test cases.
7. Recommendations explain their underlying calculations.
8. The AI assistant can answer inventory questions using real application data.
9. AI failure does not disable core inventory operations.
10. A purchase recommendation can be reviewed, edited, approved or rejected.
11. CSV import validates data and reports errors.
12. CSV export produces usable reports.
13. The application runs locally and through Docker.
14. Automated tests and documented setup instructions are available.

## 11. Success measures for the demonstration

Demonstrate the following using a realistic sample business dataset:

- A product being created and stocked.
- Sales reducing its stock.
- The reorder engine identifying a low-stock product.
- A suggested quantity being calculated and explained.
- The AI assistant answering a question using the same records.
- A manager reviewing and approving a draft purchase recommendation.
- An exported inventory report.

The demonstration must use traceable sample data, not fabricated live business results.

## 12. Four-week delivery plan

**Week 1 — Foundation**
- Confirm architecture and repository structure.
- Establish backend and frontend projects.
- Configure database and initial models.
- Implement product management.
- Implement inventory movement foundations.
- Add sample data and initial automated tests.

**Week 2 — Inventory intelligence**
- Complete stock movement workflows.
- Implement sales records.
- Implement deterministic reorder calculations.
- Build low-stock alerts and dashboard summaries.
- Add calculation and API tests.

**Week 3 — AI and procurement**
- Implement AI assistant integration.
- Add evidence-based inventory explanations.
- Implement purchase recommendations.
- Add human approval and rejection workflows.
- Implement CSV import and export.

**Week 4 — Product readiness**
- Complete frontend workflows.
- Test end-to-end scenarios.
- Fix bugs and improve validation.
- Add Docker deployment.
- Complete README and technical documentation.
- Prepare demonstration data, video and competition presentation.

## 13. Engineering principles

1. Correct inventory data takes priority over AI-generated explanations.
2. Business calculations must be deterministic and independently testable.
3. AI must not have unrestricted database write access.
4. Every stock change must have a traceable movement record.
5. Purchasing actions require human approval.
6. Build the smallest complete workflow before adding optional features.
7. Every significant Codex change must be reviewed and tested.
8. Do not commit credentials, personal business data or secrets.

---

**Document status:** Initial requirements baseline — ready for implementation review.

**Version:** 1.0