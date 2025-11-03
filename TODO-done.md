# Proofs App Development Plan

This document outlines the development tasks for improving the Proofs App.

## Phase 1: Customer Integration

- [x] **1.1: Create `Customer` Model**: Add a new `Customer` table to `app/models.py` with fields for `name`, `company_name`, and `email`.
- [x] **1.2: Generate Database Migration for Customer**: Create a new Alembic migration script for the `Customer` model.
- [x] **1.3: Associate `Proof` with `Customer`**: Add a foreign key to the `Proof` model to link it to a `Customer`.
- [x] **1.4: Generate Database Migration for Association**: Create a new Alembic migration script for the `proofs.customer_id` column.
- [x] **1.5: Update Upload Process**: Modify the `/upload` route and template to allow selecting or creating a `Customer` when uploading a new proof.
- [x] **1.6: Implement Customer Management UI**: Create a new section in the admin dashboard for full CRUD (Create, Read, Update, Delete) management of Customers.

## Phase 2: Proof Versioning

- [x] **2.1: Implement "New Version" Upload**: Create a route and UI to allow designers to upload a new version to an existing `Proof`.
- [x] **2.2: Display Version History**: Update the client-facing proof page to show a history of all associated `ProofVersion` records.
- [x] **2.3: (Advanced) Side-by-Side Version Comparison**: Build a view to display two proof versions next to each other for easier comparison.

## Phase 3: Advanced Features & Refinements

- [x] **3.1: (Advanced) On-Proof Annotations**: Integrate a JavaScript library to allow clients to leave comments directly on the proof file.
- [x] **3.2: Improve Security**: Implement a customer login system to replace reliance on public shareable links.
- [x] **3.3: Refactor Codebase**: Break the monolithic `app.py` into smaller, more manageable Flask Blueprints.
- [x] **3.4: Establish Testing Framework**: Set up `pytest` and write initial tests for core functionality.