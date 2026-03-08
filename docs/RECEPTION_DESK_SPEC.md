# Reception Desk Spec

> Temporary planning file for the Reception Desk + Manager Review workflow.
> For the frozen first implementation contract, see `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`.
> Delete this file after the feature is fully implemented and the final docs are updated.

## Goal

Create a simple, safe workflow where:

- the receptionist does the main daily entry work
- the manager reviews and approves before anything goes live
- patient matching errors are reduced as much as possible
- the UI stays simple for low-skill staff, elderly managers, and new employees

## Core Principles

- Simple for staff, strict for data.
- Receptionist records the event, not the final truth.
- Nothing touches live patient, treatment, or payment data until manager approval.
- The system may suggest a patient, but it must never silently route live data on its own.
- Duplicate cleanup and merging are separate from the daily review workflow.

## Receptionist Access

Receptionist should keep access to:

- Reception Desk
- Patient List for lookup/review
- Appointments

Reception Desk should become the main daily entry page.

Receptionist should also have contextual draft entry points later:

- `+ Treatment Entry`
- `+ Payment Entry`

These are draft-entry actions only and should include helper text such as:

- `Sent for manager review`

They must stay separate from manager live actions like `+ Add Treatment` and `+ Add Payment`.

## Entry Modes

The workflow should support 3 separate entry modes. This is a critical design rule.

### 1. From Reception Desk

Use this when the patient is not yet confirmed.

- patient is not locked
- receptionist may search or type manually
- matching is required
- manager review may need patient confirmation

### 2. From Patient File

Use this when the receptionist already opened the correct patient file.

- patient is locked
- receptionist should not retype name or phone
- patient identity is shown read-only at the top of the form
- form should include a clear escape like `Wrong patient? Cancel and search again`

### 3. From Treatment Card

Use this when the receptionist knows the payment belongs to a specific treatment.

- patient is locked
- treatment is locked
- receptionist should not choose the patient again
- receptionist should not choose the treatment again
- both patient and treatment context are shown read-only at the top of the form

## Entry Source Confidence

Manager review should take the entry source into account:

- `Started from treatment card` = strongest context
- `Started from patient file` = strong context
- `Started from Reception Desk` = weaker context unless matching is strong

This should affect review speed and how aggressively the system shows alternate patient suggestions.

## Reception Desk Form

### Section 1: Patient

- `Page number` optional
- `Name` required
- `Phone` optional

### Section 2: Visit

- `Visit type` optional
  - blank
  - Consultation
  - Diagnosis
  - Follow up
- `Treatment` plain text
- `Doctor` required

### Section 3: Payment

- `Money received today?` yes/no
- If `No`, hide payment fields
- If `Yes`, show:
  - `Paid today` required
  - `Total` optional
  - `Discount` optional
  - `Remaining` auto-calculated, read-only, only when `Total` exists

### Section 4: Notes

- `Note` optional but important

## Receptionist Rules

- Receptionist never types `Remaining`.
- `Discount` defaults to `0` if blank.
- If only `Paid today` is known, receptionist can still submit.
- File number is not entered by receptionist.
- If entry started from patient file, receptionist does not type name or phone again.
- If entry started from treatment card, receptionist does not type patient or treatment again.
- Receptionist never chooses:
  - existing vs new treatment
  - final patient routing
  - final payment routing
  - merging

## Matching Rules

The system should match in the background using:

- phone
- page number
- Arabic name similarity
- all saved phone numbers in the patient file
- all saved page numbers in the patient file

If a patient file has multiple phone numbers or page numbers, that should help matching automatically without adding extra decisions for the receptionist.

## Receptionist Warnings

Use soft warnings where possible:

- Phone missing
- Page number missing
- Possible patient match found
- Multiple possible matches
- Total missing
- Remaining unknown

Use hard blocks only for obvious bad input:

- Name missing
- Doctor missing
- Money received = Yes but Paid today missing
- Paid today greater than Total - Discount when Total exists

## After Receptionist Saves

- Entry goes to Pending Review
- Entry does not touch live patient/payment/treatment data
- System stores:
  - the receptionist entry
  - match suggestions
  - warning flags
  - entry source (`Reception Desk`, `Patient File`, or `Treatment Card`)

## Manager Queue Statuses

- `New`
- `Edited`
- `Held`
- `Approved`
- `Rejected`

Optional sorting/status helpers later:

- `Needs patient review`
- `Needs treatment review`

## Manager Actions

- `Approve`
- `Edit`
- `Choose different patient`
- `Hold`
- `Reject`

## Manager Review Screen

Manager should see:

- receptionist entry summary
- entry source
- top patient suggestion if available
- why the patient was suggested
  - matched by phone
  - matched by page
  - matched by Arabic name
  - matched by combined clues
- compact patient summary
  - name
  - main phone
  - file number
  - page summary
  - last visit
  - overall balance
- warning chips
  - Weak match
  - Multiple possible patients
  - Total missing
  - Money only
  - Needs treatment review

## Multiple Suggested Patients

Manager should not need a new tab for normal review.

If more than one patient is suggested:

- show compact candidate cards inline
- each card shows:
  - full name
  - main phone
  - file number
  - page summary
  - last visit
  - overall remaining
  - reason for match
- each card can open inline details, not a new tab

Inline details may show:

- all phone numbers
- all page numbers
- current treatment summary
- recent payments
- patient notes

If still unclear, manager should use `Hold`, not guess.

If the entry started from patient file or treatment card and there is no conflict:

- show the locked source patient first
- do not immediately dump alternate similar patients
- only show alternate matches when the system detects a conflict or the manager asks to see other matches

## Manager Edit Rule

- `Edit` changes only the pending draft
- `Edit` never changes live data
- after editing, item status becomes `Edited`
- manager returns to review and then decides whether to approve, hold, or reject

## Approval Outcomes

When a manager approves, the system should do one of these:

- Record visit only
- Attach payment to existing treatment
- Create new treatment

This decision should be visible at approval time.

## Routing Safety Rules

- The system may suggest a patient, but it must never auto-post live data.
- Manager must always confirm before anything goes live.
- If approving into an existing treatment:
  - receptionist entry must not silently overwrite live treatment totals
  - live treatment remains the source of truth
- If approving as a new treatment:
  - receptionist values become the draft basis
  - manager approval is still required before posting live

## Held and Rejected

### Held

- item stays out of live data
- item remains available for later review
- item can be reopened and edited later

### Rejected

- item stays out of live data
- item moves to a rejected archive
- rejection should require a reason
- item may be restorable later by manager/admin if needed

## UI Direction

- Keep the existing app shell and design language
- Make the workflow simpler than the rest of the app
- One-column forms
- Big labels
- Big buttons
- Calm card layout
- Arabic-first friendly
- Expand details only when needed

## Simple Workflow Map

```text
Receptionist opens Reception Desk
-> enters patient + visit + payment info
-> system checks matches and warnings
-> receptionist saves
-> entry goes to Pending Review

Manager opens Pending Review
-> sees summary + patient suggestion + warnings
-> Approve, Edit, Choose different patient, Hold, or Reject

If Approve
-> show final confirmation
-> then post to live records

If Edit
-> save pending draft only
-> return to review
-> approve later if correct
```

## Explicitly Out of Scope For This File

- Merge Center design
- Duplicate cleanup workflow
- Admin placement of Merge Center
- Full appointments redesign
- Full patient list permission redesign
- Full implementation phase map (see `docs/RECEPTION_DESK_PHASES.md`)

## Current Open Questions

- Exact final approval screen content
- Exact warning thresholds for weak vs strong patient matches
- Exact routing UI for choosing existing treatment vs new treatment at approval time
- Whether receptionist should see live match suggestions before saving, or only passive warnings
