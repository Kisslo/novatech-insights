# Article and LinkedIn draft storage proposal

Status: Draft for discussion with Nedal and Turker.
No SQL migration or database change is included.

## Goal

Support the path from a selected topic and Kisslo's angle to
article and LinkedIn drafts that Kisslo can review before publishing.

Keep the initial top-five presentation simple.
Extra research and counterarguments are not required for every topic.

## Current evidence

- Migration 008 creates posts for topic selection and Telegram replies.
- The inspected live posts table has:
  id, topic_id, status, kisslo_angle, telegram_chat_id,
  telegram_prompt_message_id.
- Existing post statuses are awaiting_angle and angle_received.
- Issue #28's earlier storage design is closed as not planned.
- Issue #30 and draft PR #31 describe local draft-file output.
- Nedal suggested extending posts for draft and publishing storage.
- The exact new fields and workflow are not yet confirmed.

## Existing behavior to preserve

- Preserve existing post IDs, topic links and Kisslo angles.
- Keep topic selection status separate from content approval.
- Match Telegram replies using both chat ID and prompt message ID.
- Preserve existing news, topics, memberships and RSS descriptions.
- Generating a draft must not automatically approve or publish it.

## Proposed storage needs

These are needs to discuss, not agreed column names or a final schema.

| Information | Purpose |
|---|---|
| Article draft | Generated Swedish article for review. |
| LinkedIn draft | Generated LinkedIn text for review. |
| Reviewer notes | Checks and uncertainties, kept out of published text. |
| Reviewed content | Identify the exact text Kisslo has approved. |
| Approval record | Record approval of that content. |
| Publication result | Record the destination URL and confirmed publish time. |
| Source references | Keep the supporting news IDs or source links traceable. |

## Questions for Nedal

- What exact fields will the content code read and write?
- Will output be stored on posts or in related tables?
- Are article and LinkedIn drafts approved independently?
- Are previous draft versions needed in the first release?
- How are reviewer notes separated from publishable text?
- How are failed or incomplete generations represented?
- Which fields are needed for source traceability?

## Questions for Turker and the publishing owner

- Which Telegram actions request changes or approve content?
- How does approval identify the exact content version?
- Does editing approved text require approval again?
- Which platform receives the article?
- How are publication failures and retries handled?
- How are duplicate publications prevented?

## Permissions and validation

Agree the fields each backend component may update.
Do not grant broad writes merely because a backend role is shared.

Before deployment, test that:
- Existing records and Telegram behavior remain compatible.
- Invalid workflow states are rejected.
- Reviewer notes are excluded from publishable output.
- Approval refers to the content intended for publication.
- Failed requests do not falsely mark content as published.

## Next step

Review this proposal with the component owners.
Then agree a minimal first-release contract and prepare a separate
migration, tests and deployment plan.