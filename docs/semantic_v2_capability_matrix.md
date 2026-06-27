# Semantic V2 Factual Capability Matrix

Generated for Phase 3. Source of truth for the structured matrix is `backend/app/cricket_analytics/capabilities.py`.

| Capability | Operation | Entities | Status | Executor | Sample-size rule | Known limitation |
|---|---|---|---|---|---|---|
| Direct player statistic | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum sample for rates/percentages | None known for covered metrics |
| Global leaderboard | aggregate | batter, bowler, team, venue | production_ready | aggregate_builder | Registry minimum for rate/percentage leaderboards | None known for covered metrics |
| Top/bottom N leaderboard | aggregate | batter, bowler, team, venue | partial | aggregate_builder | Registry default plus parsed minimum sample | Explicit natural-language minimum-sample parsing is limited |
| Player comparison | player_compare | batter, bowler | production_ready | player_compare_executor | Shows balls/legal balls where available | Mixed batter-vs-bowler comparisons are rejected |
| Batter-versus-bowler matchup | matchup | matchup, batter, bowler | production_ready | matchup_executor | Soft low-sample flag | None known for tested shapes |
| Which bowler against this batter | matchup | bowler | production_ready | matchup_executor | Soft low-sample flag | None known for tested shapes |
| Phase-filtered metric | aggregate | batter, bowler, team | production_ready | aggregate_builder | Registry minimum after phase filter | None known for covered phases |
| Year-filtered metric | aggregate | batter, bowler, team | production_ready | aggregate_builder | Registry minimum after year filter | Competition phrasing is narrower than year phrasing |
| Opposition-filtered metric | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum after role-aware opposition filter | Team-level opposition semantics remain unsupported |
| Venue-filtered metric | aggregate | batter, bowler, venue | production_ready | aggregate_builder | Registry minimum after venue filter | Tested aliases covered; unseen aliases need resolver entries |
| Line breakdown | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum by line bucket | None known for tested shapes |
| Length breakdown | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum by length bucket | None known for tested shapes |
| Shot-type breakdown | aggregate/special | batter | production_ready | aggregate_builder or batting profile handler | Balls by shot type | Compound “where and shots” uses profile handler |
| Field-zone breakdown | aggregate/special | batter | production_ready | aggregate_builder or batting profile handler | Balls by hand-adjusted zone | Compound “where and shots” uses profile handler |
| Bowling-style split | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum by style bucket | None known for tested style groups |
| Batter-hand / bowler-hand split | aggregate | batter, bowler | partial | aggregate_builder | Registry minimum by hand bucket | Bowler hand is derived coarsely from style |
| Split comparison | split_compare | batter, bowler, team | production_ready | split_compare_executor | Both sides must satisfy sample threshold | Supported split types only |
| Line/length filtered player statistic | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum after line/length filter | None known for tested shapes |
| Yorker volume and percentage | aggregate | bowler | production_ready | aggregate_builder | Legal-ball minimum for percentage | None known for tested shapes |
| False-shot and control metrics | aggregate | batter, bowler | production_ready | aggregate_builder | Registry minimum for rates | `control_percentage` remains ontology-compatible but not in Phase 1 migrated registry |

Unsupported factual requests must stay unsupported rather than falling back to legacy in normal Atlas chat.
