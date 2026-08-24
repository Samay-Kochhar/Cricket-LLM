# CricAtlas Analysis Language

This glossary keeps question types and readiness claims consistent across CricAtlas product and engineering documents.

## Question Types

**Standalone question**:
A question containing all the player, metric, and filter information needed to answer it without earlier chat messages.
_Avoid_: Single-level question

**Comparison question**:
A question that compares two or more players using the same supported metrics and filters.
_Avoid_: Multi-query question, multi-level question

**Contextual follow-up**:
A new question that inherits the previous player, metric, and filters unless the user explicitly replaces them. Material ambiguity requires clarification.
_Avoid_: Template question

**Conversation state**:
The structured record of players, metric, comparison participants, and filters from the last successful answer that a contextual follow-up can inherit. Chat transcript inference is only a compatibility fallback.
_Avoid_: Chat history, transcript context

**Analyst workup**:
A broad analysis request that gathers several different evidence views before producing a conclusion, such as a bowling plan for a named batter.
_Avoid_: Comparison question, multi-level question

**Suggested follow-up**:
A question offered by CricAtlas after an answer and intended to be sent within the same conversation.
_Avoid_: Template

**Clarification option**:
A choice offered when CricAtlas needs the user to resolve material ambiguity before analysis, such as choosing batting or bowling strike rate. It is required to complete the current question and is not a suggested follow-up.
_Avoid_: Suggested follow-up, recommendation

## Readiness

**Product-ready**:
A question family that passes its exact real chat flow, including displayed suggested follow-ups, and is reliable enough to show users.
_Avoid_: Implemented, backend-ready, tests pass

**Descriptive comparison**:
A comparison that reports players’ actual statistics without claiming that a value is best, worst, or generally superior. Sample size is shown as context, not treated as a warning.
_Avoid_: Ranking

**Ranking**:
An ordered best, worst, highest, or lowest result that uses a default minimum of 60 balls unless the user chooses another threshold.
_Avoid_: Descriptive comparison

## Metrics

**Batting strike rate**:
Runs scored per 100 balls faced. Higher means faster scoring.
_Avoid_: Strike rate when the role is unclear

**Bowling strike rate**:
Legal balls bowled per bowler-credit wicket. Lower means more frequent wickets; it is unavailable when the bowler has taken no wickets.
_Avoid_: Balls per wicket, strike rate when the role is unclear

**Ambiguous strike rate**:
Any unqualified strike-rate request that does not say batting or bowling. It requires the user to choose the metric before CricAtlas calculates an answer.
_Avoid_: Guessing from the most recent role
