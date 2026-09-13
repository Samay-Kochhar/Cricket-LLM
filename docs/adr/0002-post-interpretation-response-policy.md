# Apply one response policy after meaning interpretation

CricAtlas applies ambiguity, capability, data, and safeguard decisions after a
candidate cricket meaning has been interpreted. The policy may request a
clarification or classify an unavailable capability or field, but it does not
rewrite the candidate's metric, operation, filters, or player roles.

A clarification is terminal only when materially different valid meanings remain.
Explicit batter or bowler wording and versioned conversation meaning resolve role
ambiguity before this decision. Deterministic capability metadata distinguishes
unsupported concepts such as weather, salaries, predictions, and unsupported team
analysis from absent fielding and captaincy fields. Only an actual planning failure
uses `planner_uncertainty`.

Sample safeguards remain an execution and presentation concern. Descriptive
answers retain their observed value and sample size. Rankings apply an explicit
threshold or the metric registry default, exclude non-qualifiers in SQL, and
disclose the threshold or return no qualified result.
