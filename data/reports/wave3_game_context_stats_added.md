# Wave3 game-context stats added

## Scope completed
Extended deterministic pregame context generation in `scripts\build_last5_backtest_features.py` and propagated schema support to:
- `scripts\build_last5_backtest_features_roster.py`
- `scripts\prepare_roster_feature_schema.py`

Outputs refreshed:
- `data\processed\backtest_features_last5.csv`
- SQLite table `backtest_features_last5` in `data\processed\nhl_research.db`
- `data\processed\backtest_features_last5_roster.csv`
- SQLite table `backtest_features_last5_roster` in `data\processed\nhl_research.db`

## Added columns

### Schedule / rest stress
- `home_three_in_four`, `away_three_in_four`
- `home_four_in_six`, `away_four_in_six`
- (existing rest columns retained) `home_pregame_rest_days`, `away_pregame_rest_days`, `home_back_to_back`, `away_back_to_back`

Definition: each stress flag is computed pregame from prior game dates only (no current-game leakage).
- `three_in_four = 1` when team had >=2 games in prior 3 days (current game is game 3 in 4-day window)
- `four_in_six = 1` when team had >=3 games in prior 5 days (current game is game 4 in 6-day window)

### Travel / venue
- `home_pregame_travel_miles`, `away_pregame_travel_miles`
- `delta_travel_miles_home_minus_away`
- `home_timezone_shift_hours`, `away_timezone_shift_hours`
- `delta_timezone_shift_hours_home_minus_away`

Definition: travel is haversine miles from each team’s previous game venue to current game venue. Timezone shift uses IANA timezone offsets on game date.

### Home stand / road trip counters
- `home_pregame_home_stand_len`, `away_pregame_home_stand_len`
- `home_pregame_road_trip_len`, `away_pregame_road_trip_len`
- `delta_home_stand_len_home_minus_away`
- `delta_road_trip_len_home_minus_away`

Definition: counters are pregame streak lengths including the current location assignment (home/away) and prior streak history only.

## Reliability notes
- Team home-venue coordinates/timezones are static proxies by franchise.
- Utah franchise handling: seasons up to `20232024` use Phoenix-area proxy; `20242025+` uses Salt Lake City proxy.
- Neutral-site and officiating context are not available in `historical_games_last5`, so officiating/arena refs were not added.

## Quick sanity snapshot (6560 games)
- `home_three_in_four` rate: **15.82%**
- `away_three_in_four` rate: **21.68%**
- `home_four_in_six` rate: **17.77%**
- `away_four_in_six` rate: **20.64%**
- `home_pregame_travel_miles` non-null: **6472** (mean **354.75**)
- `away_pregame_travel_miles` non-null: **6488** (mean **644.67**)
- `home_timezone_shift_hours` non-null: **6472** (max abs **4.0**)
- `away_timezone_shift_hours` non-null: **6488** (max abs **4.0**)

## Leakage safety guardrail
All added context features are calculated strictly from state known before puck drop for the target game. Team states are updated only after the current row is emitted.
