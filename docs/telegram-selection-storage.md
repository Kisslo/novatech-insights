# Telegram Selection Storage

Migration: sql/008_create_topic_status_and_posts.sql

Status: implemented and tested locally; CI and review pending.
No shared Supabase changes have been made during this work.

## Responsibilities

- Python prepares topic labels and Telegram presentation.
- n8n sends messages, handles callbacks and saves Kisslo's angle.
- Supabase stores workflow state.
- Nosheen and Turker coordinate migration deployment.

## Topic status

topics.status is required and defaults to new.

Allowed values:

| Value | Meaning |
|---|---|
| new | Topic has not yet been marked as shown. |
| shown | Telegram message was successfully sent. |
| selected | Kisslo pressed Skriv. |
| skipped | Kisslo pressed Skippa. |

Existing topics receive new when migration 008 is applied.
This is workflow status, not topic freshness or retirement.

n8n manages transitions. The database validates allowed values but does
not enforce transition order.

When marking a message shown, update only topics still in new state,
so retries do not overwrite selected or skipped.

## Posts

| Column | Rule |
|---|---|
| id | Generated bigint identity primary key. |
| topic_id | Required, unique reference to topics.id. |
| status | Required; defaults to awaiting_angle. |
| kisslo_angle | NULL while waiting; nonblank when received. |
| telegram_chat_id | Required, nonzero bigint; negative chat IDs are allowed. |
| telegram_prompt_message_id | Nullable initially; positive bigint when recorded. |

Allowed post statuses are awaiting_angle and angle_received.

The pair (telegram_chat_id, telegram_prompt_message_id) is unique when
the prompt message ID is present.

A topic referenced by a post cannot be deleted.

## Skriv flow

1. Find or create the post for topic_id.
2. A new post has status awaiting_angle and kisslo_angle NULL.
3. Record telegram_chat_id when creating the post.
4. Mark the topic selected as part of the coordinated n8n workflow.
5. Send the angle question using force_reply.
6. Record the returned message ID in telegram_prompt_message_id.
7. Match replies using both chat ID and reply_to_message.message_id.
8. Save kisslo_angle and status = angle_received in the same update.

When receiving an angle, update only the matching awaiting_angle post.
Do not overwrite an already received angle on a duplicate event.

topic_id is unique to prevent duplicate post rows. On a conflict, fetch
and reuse the existing post. Do not overwrite it with default values.

Database uniqueness prevents duplicate rows, not duplicate Telegram
messages. n8n must also handle callback retries and partial failures.

Creating the post, changing topic status and sending Telegram messages
are separate operations. No cross-service transaction is implemented.

## Replies without an explicit reply reference

If exactly one post is awaiting an angle in the same chat, n8n may use
that post according to the agreed fallback.

If none or several are pending, ask Kisslo to reply directly to the
correct question. Do not guess the topic.

## Permissions

service_role receives:

- UPDATE on topics.status.
- SELECT on posts.
- INSERT on the five application fields in posts.
- UPDATE on status, kisslo_angle and telegram_prompt_message_id.
- USAGE on posts_id_seq.

It cannot update post IDs, topic_id or telegram_chat_id through these
grants, and receives no DELETE permission on posts.

posts has RLS enabled. Automatic grants are removed from PUBLIC, anon,
authenticated and service_role before the explicit grants are applied.

All programs using service_role share these permissions.

If migration 006 is rerun, it resets topic grants, including the status
UPDATE grant added by 008. Do not blindly rerun earlier migrations.

## Verification

The local test passed and rolled back its fixture data.

Verified:

- Topic defaults and valid status updates.
- Rejection of invalid topic status.
- Pending post defaults.
- Duplicate topic protection.
- Unique chat/prompt matching.
- Equal message IDs in different chats are allowed.
- An angle updates the correct post.
- Invalid post states and whitespace-only angles are rejected.
- Missing topic references are rejected.
- Backend topic/chat identity updates and post deletion are denied.
- Linked topic deletion is restricted.
- RLS is enabled and anon/authenticated lack direct data access.

CI applies 008 after the migration 007 test and runs the new test in both
database setups.

Live REST access and the complete Telegram flow remain unverified.

## Deployment order

1. Apply migrations 002–006 under the agreed deployment plan.
2. Run and verify the source-normalization backfill.
3. Confirm zero NULL source keys and apply migration 007.
4. Apply migration 008.
5. Verify API permissions and n8n operations.
6. Run the Telegram selection-and-angle test.

Do not rerun migration 001 against existing production news.
Never run local/CI setup scripts in real Supabase.

## Deferred decisions

- Selecting the same topic again later.
- Expiration or cancellation of unanswered prompts.
- Later draft, approval and publication states.
- Topic retirement and reactivation.

Migration 008 supports the initial selection-and-angle workflow only.