# Novatech Insights

A system for collecting relevant news and developing it into content
for the Novatech Solutions website and LinkedIn.

The system will support an editorial workflow in which news is
grouped, prioritized, and summarized to support the creation of
articles, LinkedIn posts, and videos.

## Purpose

Increase Novatech Solutions' visibility on Google and LinkedIn
through relevant content based on current news and the company's
perspective.

## Planned Functionality

- Collect news information from selected sources.
- Identify and handle duplicates.
- Group news into topics.
- Summarize news to support editorial review.
- Produce articles for novatech-solutions.se and short LinkedIn
  posts based on Kisslo's arguments.
- Verify the sources used to develop the content.
- Support a workflow for review, approval, and publication.
- Rank topics using a model trained on Kisslo's ratings.
- Evaluate the model based on the proportion of suggestions
  Kisslo actually uses.
- Create short videos from approved articles using Videofy.

## Requirements and Constraints

- Source text must not be copied into the system.
- LinkedIn must not be read automatically.
- Topic or genre information must be considered when defining
  the news data structure, based on Kisslo's feedback.
- News collection and topic grouping must account for the four
  to five search phrases and services Kisslo has identified as
  priorities. The specific list needs to be documented and
  must support future expansion.
- The Videofy integration must include Python code that sends
  articles to Videofy and a customer configuration file in JSON
  containing a logo, voice settings, and AI instructions.

## Delivery Milestones

### Week 1 — Project Foundation

Week 1 is allocated to establishing the project foundation.

Proposed scope:
- Prepare the shared repository and project documentation.
- Establish a common foundation for local development
  and configuration.
- Clarify responsibilities and how information will be
  transferred between components.

Stretch goal: complete an initial successful retrieval of a
news article from a selected source.

The scope and acceptance criteria for successful retrieval
need to be defined before the test is carried out.

### By the End of Week 2

- At least 30 news sources.
- The first week's news grouped into topics.

### From Week 5

- Each approved article must also be turned into a short
  video using Videofy.

## Preliminary Responsibility Assignment

| Area | Assigned to | Scope |
|---|---|---|
| Data | Nosheen | News retrieval, duplicate handling, and results measurement. Python code for transferring articles to Videofy. |
| Topics | Mathias, Turker | News grouping and an ML model that ranks topics based on Kisslo's ratings. Evaluation of the ranking. |
| Content | Nedal | Summaries, content drafts, source verification, and the publication workflow. Customer configuration file in JSON for Videofy. |

The areas follow the project brief. The assignment of individuals
is preliminary.

Interfaces between components and responsibility for shared
components need to be clarified. Responsibility for the publication
workflow does not automatically grant authority to approve or
publish content.

## Status

The project is in its initial setup phase. The architecture,
shared development environment, and deployment approach have
not yet been finalized.

n8n has been mentioned as a possible automation tool but has
not been confirmed as a technology choice.

## Proposed Initial Grouping Test

An initial test has been proposed in which news items are
grouped based on their titles.

Proposed core fields:
- title
- link
- source
- publication_date

Kisslo has also identified topic or genre as relevant information.
Its representation and assignment need to be defined.

Title-based grouping is a test proposal, not a decision about
the system's final analysis method.

## Open Questions

- Selection of tools, services, and integrations.
- Storage and handling of news data and generated content.
- Data formats and interfaces between components.
- Documentation of priority search phrases and services.
- Definition and assignment of topics or genres.
- Processes and authority for review, approval, and publication.
- Definition of the results metrics owned by the Data area.
- Shared Python version and dependency management.
- Target environment for deployment and ongoing maintenance.

## Development

Instructions for local installation, configuration, and testing
will be added once the development environment has been
defined and verified.