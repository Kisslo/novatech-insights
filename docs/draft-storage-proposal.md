# Article and LinkedIn draft storage

Status: Implemented locally for review in PR #60.
Migration 010 has not been deployed to shared Supabase.

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
- draft_generated
- changes_requested

Call through POST /rest/v1/rpc/save_post_draft using the backend role.
Nedal's client must use this function instead of separate insert
and status-update requests.

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
sql/test_post_drafts.sql passed checks for:
- Draft version allocation and saved content.
- Saving from angle_received, draft_generated and changes_requested.
- Rejection before an angle and after approval.
- Unchanged drafts and status after invalid content.
- RLS and backend permissions.

CI applies migration 010 and runs the test in both test databases.

## Decisions still needed

- Duplicate requests: locking prevents version collisions, but each
  successful call creates a version. Retries are not deduplicated.
- How approval identifies the exact draft version.
- Whether article and LinkedIn content are approved together.
- Editing approved content and requesting approval again.
- Publication destination, retries and duplicate prevention.
- Whether source-ID validation needs stronger database rules.

## Deployment

Review the migration and coordinate client compatibility first.
After merge, agree deployment timing with the team.
Do not rerun migration 008 on an existing posts table.
Deploy migration 010 separately, then verify backend RPC access.