# Article and LinkedIn draft storage

Status: Implemented locally for review in PR #60.
Migration 010 has not been deployed to shared Supabase.
The latest status-guard changes still need to be pushed and checked in CI.

## Goal

Save versioned article and LinkedIn drafts for review.
Generating a draft does not approve or publish it.
Keep the initial top-five presentation simple.

## Storage

Migration: sql/010_create_post_drafts.sql

The post_drafts table contains:
- id
- post_id: references posts.id
- version: positive integer, unique per post
- article_text: nonblank text
- linkedin_text: nonblank text
- reviewer_notes: text kept separate from publishable content
- source_news_ids: bigint array
- stance: agree or rebut
- created_at

Draft versions preserve earlier generated content.
Source IDs are stored as references; array elements do not have
foreign-key validation in this migration.

## Backend function

save_post_draft(
    p_post_id bigint,
    p_article_text text,
    p_linkedin_text text,
    p_reviewer_notes text,
    p_source_news_ids bigint[],
    p_stance text
)

Returns one row containing draft_id and version.

The function:
1. Locks the post with SELECT FOR UPDATE.
2. Rejects a missing post or a disallowed status.
3. Allocates the next version for that post.
4. Inserts the draft.
5. Sets posts.status to draft_generated.

These operations are atomic: an error rolls back the function's writes.

Allowed starting statuses:
- angle_received
- changes_requested

Saving from draft_generated is rejected.
A later version requires the post to enter changes_requested.

The post lock serializes concurrent saves for the same post.
After one save succeeds, a second waiting save sees draft_generated
and is rejected.

This is a status guard, not request-ID-based idempotency.
A repeated call returns an error rather than the previous result.
A delayed request arriving after a later changes_requested transition
cannot be identified as an old request by this function.

## API and n8n integration

The backend calls:
POST /rest/v1/rpc/save_post_draft

Nedal's endpoint in PR #68 must use this function instead of separate
draft-insert and status-update requests.

The proposed n8n integration calls:
POST /drafts/{post_id}

n8n must stop inserting draft rows directly before the new shared
workflow is enabled.

## Stance

The agreed initial direction is agree as the endpoint default.
The database function requires an explicit agree or rebut value
and stores it on each draft version.

Collecting stance through Telegram is later work.
The proposed interaction is a choice after Kisslo supplies his angle.

## Post statuses

Existing statuses are preserved:
- awaiting_angle
- angle_received

New allowed values:
- draft_generated
- awaiting_approval
- approved
- changes_requested
- publish_requested
- published

All states after awaiting_angle require a nonblank Kisslo angle.
Allowing these values does not implement approval or publishing.
Topic selection status remains separate from post status.

draft_kept and storage for Kisslo's requested changes are outside
this migration and are planned as follow-up work.

## Permissions

The function follows the existing SECURITY DEFINER pattern with
search_path fixed to pg_catalog.

service_role can read drafts and execute save_post_draft.
Direct draft writes are not granted to application roles.
Existing posts permissions remain unchanged.

Reviewer notes must be excluded by the publishing application.
Separate storage does not itself prevent their publication.

## Validation

Local migration execution passed.
The function was subsequently updated locally with the new status guard.
The updated sql/test_post_drafts.sql passed checks for:
- Draft version allocation and saved content.
- Saving from angle_received and changes_requested.
- Rejection before an angle and after approval.
- Rejection of repeated saves from draft_generated without data changes.
- Unchanged drafts and status after invalid content.
- RLS and backend permissions.
- Calling the function under SET LOCAL ROLE service_role and verifying
  the saved draft and post status.

CI applies migration 010 and runs the test in both test databases.
The latest changes require a new CI run after they are pushed.

## Existing shared Supabase table

A different post_drafts table already exists in shared Supabase.
It uses article_draft, linkedin_draft, sources and editorial_note,
and also contains status and updated_at.

The inspected table contains two n8n test rows:
- Draft ID 1: post_id 2, version 1.
- Draft ID 2: post_id 2, version 1.

Migration 010 cannot run while that table retains the post_drafts name.
Its duplicate post/version pairs also conflict with the new unique rule.

The proposed deployment approach is to preserve the old table under
an agreed legacy name, then create the new table using migration 010.
No existing rows have been changed or deleted.

Before renaming, coordinate with Turker and Nedal and inspect dependent
objects, indexes and sequences for conflicts with the new migration.
Renaming a table alone does not rename all of its related objects.

Legacy rows are not automatically copied into the new table.
Any later data migration requires an agreed mapping and version policy.

## Decisions and follow-up work

- Confirm the legacy-table preservation and dependency-handling plan.
- Complete n8n and endpoint integration.
- Decide how approval identifies the exact draft version.
- Decide whether article and LinkedIn content are approved together.
- Define editing and reapproval of approved content.
- Define publication destination, retries and duplicate prevention.
- Decide whether source-ID validation needs stronger database rules.
- Add draft_kept and change-request storage in a later migration.

## Deployment

Review the latest changes and confirm passing CI before merge.
Coordinate deployment timing with Turker and Nedal.

Before deployment:
1. Confirm the shared table's current structure and data.
2. Agree how to preserve the old table and handle dependencies.
3. Coordinate stopping direct n8n writes to the old draft workflow.
4. Confirm Nedal's endpoint uses the RPC function.

Then apply the agreed legacy-table changes and migration 010.
Do not rerun migration 008 on an existing posts table.
Verify the new table, constraints, permissions and backend RPC access.
Coordinate a real integration run with Nedal after deployment.