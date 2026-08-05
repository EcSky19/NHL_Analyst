(function () {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const state = {
    league: 'nhl',
    view: 'standings',
    paused: false,
    mock: new URLSearchParams(location.search).get('mock') === '1',
    search: '',
    sort: { key: 'points', dir: 'desc' },
    groupStandings: true,
    scheduleDate: '',
    scheduleWeek: '',
    failureCount: 0,
    timer: null,
    cache: {},
    teams: [],
    selectedTeam: null,
    playerStat: 'points',
    playerTeam: '',
    playerGroup: 'hitting',
    darkManual: localStorage.getItem('sports-ui-theme') || ''
  };

  const endpoints = {
    standings: (league) => `/api/${league}/standings`,
    teams: (league) => `/api/${league}/teams`,
    players: (league) => `/api/${league}/players?stat=${encodeURIComponent(state.playerStat)}&limit=50${state.playerTeam ? `&team=${encodeURIComponent(state.playerTeam)}` : ''}${league === 'mlb' ? `&group=${encodeURIComponent(state.playerGroup)}` : ''}`,
    schedule: (league) => league === 'nfl'
      ? `/api/nfl/schedule${state.scheduleWeek ? `?week=${encodeURIComponent(state.scheduleWeek)}` : ''}`
      : `/api/${league}/schedule${state.scheduleDate ? `?date=${encodeURIComponent(state.scheduleDate)}` : ''}`,
    predictions: (league) => `/api/predictions/${league}`,
    matchup: (league, home, away) => `/api/predictions/matchup?league=${encodeURIComponent(league)}&home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`
  };


  const leagueConfig = {
    nhl: {
      scoreFor: 'Goals for', scoreAgainst: 'Goals against', scoreForShort: 'GF', scoreAgainstShort: 'GA',
      standingsNote: 'One shared standings table handles NHL, NFL, NBA, and MLB through the contract\'s common row shape.',
      playerStats: ['points', 'goals', 'assists', 'plus_minus', 'shots'],
      defaultPlayerStat: 'points'
    },
    nfl: {
      scoreFor: 'Points for', scoreAgainst: 'Points against', scoreForShort: 'PF', scoreAgainstShort: 'PA',
      standingsNote: 'One shared standings table handles NHL, NFL, NBA, and MLB through the contract\'s common row shape.',
      playerStats: ['passing_yards', 'passing_tds', 'interceptions', 'rushing_yards', 'fantasy_points'],
      defaultPlayerStat: 'passing_yards'
    },
    nba: {
      scoreFor: 'Points for', scoreAgainst: 'Points against', scoreForShort: 'PF', scoreAgainstShort: 'PA',
      standingsNote: 'NBA games cannot tie, so this view shows W-L and win percentage without tie or overtime-loss columns.',
      playerStats: ['points', 'rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'minutes'],
      defaultPlayerStat: 'points'
    },
    mlb: {
      scoreFor: 'Runs scored', scoreAgainst: 'Runs allowed', scoreForShort: 'RS', scoreAgainstShort: 'RA',
      standingsNote: 'MLB is in its regular season, so games played and games behind show partial-season context from live standings.',
      playerGroups: {
        hitting: ['avg', 'ops', 'homeRuns', 'rbi', 'runs', 'hits', 'stolenBases'],
        pitching: ['era', 'whip', 'wins', 'strikeOuts', 'saves', 'inningsPitched']
      },
      playerStats: ['avg', 'ops', 'homeRuns', 'rbi', 'runs', 'hits', 'stolenBases'],
      defaultPlayerStat: 'avg'
    }
  };

  const sample = {
    nhl: {
      standings: [
        row('TOR', 'Toronto Maple Leafs', 'Eastern', 'Atlantic', 1, 82, 50, 25, 7, null, 107, 303, 260, 'W3', '7-2-1'),
        row('BOS', 'Boston Bruins', 'Eastern', 'Atlantic', 2, 82, 47, 29, 6, null, 100, 286, 247, 'L1', '6-3-1'),
        row('COL', 'Colorado Avalanche', 'Western', 'Central', 1, 82, 49, 27, 6, null, 104, 312, 268, 'W2', '8-2-0'),
        row('VAN', 'Vancouver Canucks', 'Western', 'Pacific', 1, 82, 46, 30, 6, null, 98, 279, 255, 'L2', '5-4-1')
      ],
      players: [
        player('Auston Matthews', 'TOR', 'C', 82, 57, 42, 99),
        player('Nathan MacKinnon', 'COL', 'C', 80, 43, 72, 115),
        player('David Pastrnak', 'BOS', 'RW', 82, 49, 55, 104)
      ]
    },
    nfl: {
      standings: [
        row('KC', 'Kansas City Chiefs', 'AFC', 'West', 1, 17, 13, 4, null, 0, 0, 438, 331, 'W4', '8-2'),
        row('BUF', 'Buffalo Bills', 'AFC', 'East', 1, 17, 12, 5, null, 0, 0, 503, 368, 'W2', '7-3'),
        row('PHI', 'Philadelphia Eagles', 'NFC', 'East', 1, 17, 14, 3, null, 0, 0, 475, 302, 'W6', '9-1'),
        row('DET', 'Detroit Lions', 'NFC', 'North', 1, 17, 13, 4, null, 0, 0, 564, 342, 'L1', '8-2')
      ],
      players: [
        player('Josh Allen', 'BUF', 'QB', 17, 41, 8, 494),
        player('Patrick Mahomes', 'KC', 'QB', 17, 32, 12, 441),
        player('Saquon Barkley', 'PHI', 'RB', 17, 15, 2, 125)
      ]
    },
    nba: {
      standings: [
        row('BOS', 'Boston Celtics', 'Eastern', 'Atlantic', 1, 82, 61, 21, null, null, 61, 9887, 9210, 'W5', '8-2'),
        row('NYK', 'New York Knicks', 'Eastern', 'Atlantic', 2, 82, 51, 31, null, null, 51, 9475, 9122, 'L1', '6-4'),
        row('OKC', 'Oklahoma City Thunder', 'Western', 'Northwest', 1, 82, 64, 18, null, null, 64, 9921, 8855, 'W3', '9-1'),
        row('DEN', 'Denver Nuggets', 'Western', 'Northwest', 2, 82, 50, 32, null, null, 50, 9670, 9433, 'W1', '7-3')
      ],
      players: [
        player('Shai Gilgeous-Alexander', 'OKC', 'G', 76, 32, 6, 32),
        player('Jayson Tatum', 'BOS', 'F', 72, 27, 6, 27),
        player('Nikola Jokić', 'DEN', 'C', 74, 29, 10, 29)
      ]
    },
    mlb: {
      standings: [
        row('TB', 'Tampa Bay Rays', 'American', 'East', 1, 114, 68, 46, null, null, 68, 562, 487, 'W2', '7-3'),
        row('TOR', 'Toronto Blue Jays', 'American', 'East', 2, 115, 65, 50, null, null, 65, 545, 510, 'L1', '6-4'),
        row('LAD', 'Los Angeles Dodgers', 'National', 'West', 1, 116, 70, 46, null, null, 70, 612, 498, 'W1', '8-2'),
        row('SF', 'San Francisco Giants', 'National', 'West', 2, 114, 61, 53, null, null, 61, 501, 492, 'L2', '5-5')
      ],
      players: [
        { name: 'Aaron Judge', player_name: 'Aaron Judge', team: 'NYY', team_abbrev: 'NYY', position: 'OF', games: 112, games_played: 112, avg: .312, ops: 1.021, homeRuns: 38, rbi: 91, runs: 86, hits: 132, stolenBases: 6 },
        { name: 'Shohei Ohtani', player_name: 'Shohei Ohtani', team: 'LAD', team_abbrev: 'LAD', position: 'DH', games: 113, games_played: 113, avg: .301, ops: .994, homeRuns: 36, rbi: 84, runs: 94, hits: 128, stolenBases: 28 },
        { name: 'Tarik Skubal', player_name: 'Tarik Skubal', team: 'DET', team_abbrev: 'DET', position: 'SP', games: 24, games_played: 24, era: 2.41, whip: .92, wins: 13, strikeOuts: 181, saves: 0, inningsPitched: 153.1 }
      ]
    }
  };
  sample.nhl.teams = sample.nhl.standings;
  sample.nfl.teams = sample.nfl.standings;
  sample.nba.teams = sample.nba.standings;
  sample.mlb.teams = sample.mlb.standings;
  sample.nhl.schedule = [game('2026-04-15', 'BOS', 'TOR', 'Final', '3-4'), game('2026-04-16', 'COL', 'VAN', 'Final', '2-5')];
  sample.nfl.schedule = [game('2026-01-04', 'KC', 'BUF', 'Final', '24-21'), game('2026-01-04', 'PHI', 'DET', 'Final', '31-28')];
  sample.nba.schedule = [game('2026-04-12', 'BOS', 'NYK', 'Final', '118-111'), game('2026-04-12', 'OKC', 'DEN', 'Final', '124-119')];
  sample.mlb.schedule = [game('2026-08-05', 'TOR', 'TB', 'Scheduled', ''), game('2026-08-05', 'TOR', 'TB', 'In Progress', '2-1'), game('2026-08-05', 'SF', 'LAD', 'Final', '4-7')];

  function row(abbrev, name, conference, division, rank, games, wins, losses, otl, ties, points, gf, ga, streak, last10) {
    return {
      team_id: abbrev, abbrev, name, conference, division, rank, games_played: games,
      wins, losses, otl, ties, points, points_pct: points ? points / (games * 2) : null,
      win_pct: wins / games, goals_for: gf, goals_against: ga, differential: gf - ga,
      streak, last10, home_record: '24-12-5', away_record: '22-15-4', logo_url: '', clinched: null
    };
  }
  function player(name, team, position, games, goals, assists, points) {
    return { name, player_name: name, team, team_abbrev: team, position, games, games_played: games, goals, assists, points, rebounds: assists, steals: goals > 10 ? 1.4 : goals, blocks: assists > 5 ? 0.8 : assists, touchdowns: goals, passing_tds: goals, passing_yards: points * 10, fantasy_points: points };
  }
  function game(date, away, home, status, score) {
    return { game_id: `${date}-${away}-${home}`, game_date: date, date, away, home, away_team: away, home_team: home, status, score };
  }

  function mockEnvelope(key) {
    const league = state.league;
    let data = key === 'predictions'
      ? samplePredictions(league)
      : sample[league][key];
    if (league === 'mlb' && key === 'players') {
      data = data.filter((p) => state.playerGroup === 'pitching' ? p.era != null || p.whip != null : p.avg != null || p.ops != null);
    }
    return Promise.resolve({
      ok: true,
      data,
      meta: {
        source: 'mock-fixture', fetched_at: new Date().toISOString(), cached: false, stale: false,
        season: league === 'nhl' ? '20252026' : league === 'nba' ? '2025-26' : '2026', season_state: league === 'mlb' ? 'regular' : 'offseason',
        season_coverage: league === 'nba' ? {
          historical_game_logs: '2001-02 through 2022-23',
          current_standings: { seasons: [{ season: '2023-24' }, { season: '2024-25' }, { season: '2025-26' }] }
        } : null
      }
    });
  }

  function samplePredictions(league) {
    const teams = sample[league].standings;
    const acc = league === 'nhl'
      ? [0.5682, 0.535, 'Model accuracy 56.82% vs 53.5% always-home baseline.']
      : league === 'nfl'
        ? [0.6611, 0.6851, 'NFL market-free accuracy 66.11%; full 67.40%; Vegas bar 68.51%, so it does not beat the market.']
        : [null, null, `${league.toUpperCase()} prediction model accuracy is not available in this mock fixture; wait for measured backend results before trusting probabilities.`];
    return [
      prediction(league, teams[0].abbrev, teams[1].abbrev, .58, acc),
      prediction(league, teams[2].abbrev, teams[3].abbrev, .52, acc)
    ];
  }
  function prediction(league, home, away, prob, acc) {
    return {
      game_id: `${league}-${home}-${away}`, game_date: '2026-09-15', league,
      home, away, home_win_prob: prob, away_win_prob: 1 - prob, confidence: 'moderate',
      model: `${league}-modest-estimator`, model_accuracy: acc[0], baseline_accuracy: acc[1],
      features_used: ['team_strength', 'rest_diff'], disclaimer: acc[2]
    };
  }

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    applyTheme();
    $('#mock-banner').classList.toggle('hidden', !state.mock);
    wireEvents();
    loadView();
    startPolling();
  }

  function wireEvents() {
    document.querySelectorAll('[data-league]').forEach((button) => button.addEventListener('click', () => {
      state.league = button.dataset.league;
      state.playerGroup = 'hitting';
      state.playerStat = leagueConfig[state.league].defaultPlayerStat;
      state.playerTeam = '';
      state.selectedTeam = null;
      state.teams = [];
      state.scheduleWeek = '';
      state.scheduleDate = '';
      if (state.league === 'mlb' && state.view === 'schedule') state.scheduleDate = todayInputDate();
      state.cache = {};
      updateActive();
      loadView(true);
    }));
    document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => {
      state.view = button.dataset.view;
      if (state.league === 'mlb' && state.view === 'schedule' && !state.scheduleDate) state.scheduleDate = todayInputDate();
      updateActive();
      loadView(true);
    }));
    $('#team-search').addEventListener('input', (event) => {
      state.search = event.target.value.trim().toLowerCase();
      renderFromCache();
    });
    $('#refresh-btn').addEventListener('click', () => loadView(true));
    $('#pause-btn').addEventListener('click', () => {
      state.paused = !state.paused;
      updatePollState();
      startPolling();
    });
    $('#theme-toggle').addEventListener('click', () => {
      state.darkManual = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('sports-ui-theme', state.darkManual);
      applyTheme();
    });
    document.addEventListener('visibilitychange', () => {
      updatePollState();
      if (!document.hidden && !state.paused) loadView();
      startPolling();
    });
  }

  function applyTheme() {
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = state.darkManual || (prefersDark ? 'dark' : 'light');
    document.documentElement.dataset.theme = theme;
    $('#theme-toggle').textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
    $('#theme-toggle').setAttribute('aria-pressed', String(theme === 'dark'));
  }

  function updateActive() {
    document.querySelectorAll('[data-league]').forEach((b) => {
      b.classList.toggle('active', b.dataset.league === state.league);
      b.setAttribute('aria-selected', String(b.dataset.league === state.league));
    });
    document.querySelectorAll('[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === state.view));
  }

  function startPolling() {
    clearTimeout(state.timer);
    if (state.paused || document.hidden) return;
    const base = state.league === 'mlb' && state.view === 'standings' ? 300000 : state.view === 'standings' ? 60000 : 120000;
    const delay = Math.min(base * Math.max(1, 2 ** Math.min(state.failureCount, 4)), 15 * 60000);
    state.timer = setTimeout(() => loadView(), delay);
  }

  function updatePollState() {
    const activeText = state.league === 'mlb' && state.view === 'standings' ? 'Auto-refresh active · MLB standings refresh about every 5 minutes' : 'Auto-refresh active';
    const text = state.paused ? 'Auto-refresh paused' : document.hidden ? 'Auto-refresh paused while tab is hidden' : state.failureCount ? `Backoff active after ${state.failureCount} failed refresh${state.failureCount > 1 ? 'es' : ''}` : activeText;
    $('#poll-state').textContent = text;
    $('#pause-btn').textContent = state.paused ? 'Resume updates' : 'Pause updates';
    $('#pause-btn').setAttribute('aria-pressed', String(state.paused));
  }

  async function loadView(force) {
    showSkeleton();
    setNotice('', 'neutral');
    try {
      await ensureTeams();
      const envelope = await getEnvelope(state.view, force);
      state.failureCount = 0;
      handleMeta(envelope.meta);
      render(state.view, envelope);
      $('#last-updated').textContent = `Last updated ${formatDateTime(envelope.meta && envelope.meta.fetched_at ? envelope.meta.fetched_at : new Date().toISOString())}`;
    } catch (error) {
      state.failureCount += 1;
      renderError(error.message || 'Could not load this view.', true);
    } finally {
      updatePollState();
      startPolling();
    }
  }

  async function ensureTeams() {
    if (state.teams.length && state.cache[`teams:${state.league}`]) return;
    try {
      const envelope = await getEnvelope('teams');
      state.teams = normalizeRows(envelope.data, 'teams');
    } catch (_) {
      state.teams = [];
    }
    if (!state.teams.length) {
      try {
        state.teams = normalizeRows((await getEnvelope('standings')).data, 'standings');
      } catch (_) {
        state.teams = state.mock ? sample[state.league].standings : [];
      }
    }
  }

  async function getEnvelope(key, force) {
    const cacheKey = `${key}:${state.league}:${state.playerStat}:${state.playerTeam}:${state.playerGroup}:${state.scheduleDate}:${state.scheduleWeek}`;
    if (!force && state.cache[cacheKey]) return state.cache[cacheKey];
    let envelope;
    if (state.mock) {
      envelope = await mockEnvelope(key);
    } else {
      try {
        envelope = await fetchEnvelope(endpoints[key](state.league), key);
      } catch (error) {
        if (key === 'predictions') {
          envelope = { ok: true, data: [], meta: { source: 'frontend-fallback', fetched_at: new Date().toISOString(), cached: false, stale: false, season_state: null, prediction_notice: error.message } };
        } else {
          throw error;
        }
      }
    }
    state.cache[cacheKey] = envelope;
    if (key === 'teams') state.cache[`teams:${state.league}`] = envelope;
    return envelope;
  }

  async function fetchEnvelope(url, label) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 9000);
    try {
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
      if (response.status === 404) throw new Error(`${title(label)} endpoint is not live yet. Try mock mode with ?mock=1 or refresh after the backend finishes.`);
      let payload;
      try {
        payload = await response.json();
      } catch (_) {
        throw new Error(`${title(label)} returned a non-JSON response.`);
      }
      if (!response.ok) throw new Error(payload && payload.error && payload.error.message ? payload.error.message : `${title(label)} request failed (${response.status}).`);
      if (!payload || typeof payload !== 'object' || !('ok' in payload)) throw new Error(`${title(label)} response did not match the API envelope.`);
      if (!payload.ok) throw new Error(payload.error && payload.error.message ? payload.error.message : `${title(label)} has no data yet.`);
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error(`${title(label)} request was slow and timed out. Auto-refresh will back off.`);
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function handleMeta(meta = {}) {
    const stale = Boolean(meta.stale);
    $('#stale-banner').classList.toggle('hidden', !stale);
    $('#stale-banner').textContent = stale ? `Showing cached data${meta.stale_reason ? `: ${meta.stale_reason}` : ' because live data is unavailable.'}` : '';
    const stateName = meta.season_state;
    const nonRegular = stateName && stateName !== 'regular';
    const liveMlb = state.league === 'mlb' && stateName === 'regular';
    $('#season-banner').className = `banner ${liveMlb ? 'info' : 'warning'}${nonRegular || liveMlb ? '' : ' hidden'}`;
    $('#season-banner').textContent = liveMlb ? `MLB regular season is live. Standings are partial-season data; last fetched ${formatDateTime(meta.fetched_at)} and auto-refresh follows the 5-minute standings TTL.` : nonRegular ? seasonStateText(meta, stateName) : '';
  }

  function renderFromCache() {
    const keys = Object.keys(state.cache).filter((key) => key.startsWith(`${state.view}:${state.league}`));
    if (keys.length) render(state.view, state.cache[keys[0]]);
  }

  function render(view, envelope) {
    const rows = normalizeRows(envelope.data, view).filter(matchesSearch);
    if (view === 'standings') renderStandings(rows, envelope.meta);
    if (view === 'teams') renderTeams(rows, envelope.meta);
    if (view === 'players') renderPlayers(rows, envelope.meta);
    if (view === 'schedule') renderSchedule(rows, envelope.meta);
    if (view === 'predictions') renderPredictions(rows, envelope.meta);
  }

  function renderStandings(rows, meta) {
    const content = $('#view-content');
    const config = leagueConfig[state.league];
    const columns = state.league === 'nba'
      ? [['rank', 'Rank'], ['name', 'Team'], ['games_played', 'GP'], ['record', 'W-L'], ['win_pct', 'Win %'], ['goals_for', config.scoreForShort], ['goals_against', config.scoreAgainstShort], ['differential', 'Diff'], ['streak', 'Streak'], ['last10', 'Last 10']]
      : state.league === 'mlb'
        ? [['rank', 'Rank'], ['name', 'Team'], ['games_played', 'GP'], ['wins', 'W'], ['losses', 'L'], ['games_behind', 'GB'], ['win_pct', 'Win %'], ['goals_for', config.scoreForShort], ['goals_against', config.scoreAgainstShort], ['differential', 'Diff'], ['streak', 'Streak'], ['last10', 'Last 10']]
      : [['rank', 'Rank'], ['name', 'Team'], ['games_played', 'GP'], ['wins', 'W'], ['losses', 'L'], ['otl', state.league === 'nhl' ? 'OTL' : 'T'], ['points', 'Pts'], ['win_pct', 'Win %'], ['goals_for', config.scoreForShort], ['goals_against', config.scoreAgainstShort], ['differential', 'Diff'], ['streak', 'Streak'], ['last10', 'Last 10']];
    if (!rows.length) {
      content.innerHTML = `${nbaCoverageMarkup(meta)}${emptyMarkup('No standings available', 'There are no rows for this search or the backend has no data yet.')}`;
      return;
    }
    const displayRows = state.league === 'mlb' ? withGamesBehind(rows) : rows;
    const sorted = sortRows(displayRows, state.sort.key, state.sort.dir);
    const grouped = state.groupStandings ? groupRows(sorted) : [['League-wide table', sorted]];
    content.innerHTML = `
      <div class="section-head">
        <div><h2>${state.league.toUpperCase()} standings</h2><p class="honesty">${escapeHtml(config.standingsNote)}</p></div>
        <button id="group-toggle" class="ghost-btn" type="button" aria-pressed="${state.groupStandings}">${state.groupStandings ? 'Show league-wide table' : 'Group by conference/division'}</button>
      </div>
      ${nbaCoverageMarkup(meta)}
      <div class="table-wrap"><table>
        <caption class="sr-only">${state.league.toUpperCase()} standings</caption>
        <thead><tr>${columns.map(([key, label]) => `<th scope="col"><button type="button" data-sort="${key}">${label} ${state.sort.key === key ? (state.sort.dir === 'asc' ? '↑' : '↓') : ''}</button></th>`).join('')}</tr></thead>
        <tbody>${grouped.map(([group, items]) => `
          <tr class="group-row"><td colspan="${columns.length}">${escapeHtml(group)}</td></tr>
          ${items.map((team) => `<tr>${columns.map(([key]) => `<td>${cell(team, key)}</td>`).join('')}</tr>`).join('')}
        `).join('')}</tbody>
      </table></div>`;
    content.querySelectorAll('[data-sort]').forEach((button) => button.addEventListener('click', () => {
      const key = button.dataset.sort;
      state.sort = { key, dir: state.sort.key === key && state.sort.dir === 'desc' ? 'asc' : 'desc' };
      renderStandings(rows, meta);
    }));
    $('#group-toggle').addEventListener('click', () => {
      state.groupStandings = !state.groupStandings;
      renderStandings(rows, meta);
    });
  }

  function renderTeams(rows, meta) {
    if (!rows.length) {
      $('#view-content').innerHTML = `${nbaCoverageMarkup(meta)}${emptyMarkup('No team stats available', 'Try clearing the team search or refreshing once routers are live.')}`;
      return;
    }
    $('#view-content').innerHTML = `
      <div class="section-head"><h2>${state.league.toUpperCase()} team stats</h2><p class="honesty">Select a card for detail. Missing fields are shown as unavailable rather than guessed.</p></div>
      ${nbaCoverageMarkup(meta)}
      <div class="cards-grid">${rows.map((team) => `
        <button class="team-card" type="button" data-team="${escapeAttr(team.abbrev || team.team_id || team.name)}">
          <div class="team-cell">${logo(team)}<div><strong>${escapeHtml(team.name || team.abbrev || 'Unknown team')}</strong><div class="abbr">${escapeHtml(team.abbrev || team.team_id || '')}</div></div></div>
          <div class="stat-grid">
            ${statBox('Record', record(team))}
            ${statBox('Win %', pct(team.win_pct))}
            ${statBox(leagueConfig[state.league].scoreFor, team.goals_for)}
            ${statBox('Differential', diff(team.differential))}
          </div>
        </button>`).join('')}</div>
      <div id="team-detail"></div>`;
    document.querySelectorAll('.team-card').forEach((card) => card.addEventListener('click', () => selectTeam(card.dataset.team)));
    if (state.selectedTeam) selectTeam(state.selectedTeam, true);
  }

  async function selectTeam(abbrev, renderOnly) {
    state.selectedTeam = abbrev;
    const container = $('#team-detail');
    const local = state.teams.find((team) => (team.abbrev || team.team_id || team.name) === abbrev) || {};
    if (!renderOnly && !state.mock) {
      try {
        const detail = await fetchEnvelope(`/api/${state.league}/teams/${encodeURIComponent(abbrev)}`, 'team detail');
        Object.assign(local, normalizeObject(detail.data));
        handleMeta(detail.meta);
      } catch (error) {
        setNotice(`Team detail endpoint was not available: ${error.message}`, 'neutral');
      }
    }
    container.innerHTML = `
      <aside class="detail-panel" aria-label="Team detail">
        <div class="section-head"><h3>${escapeHtml(local.name || abbrev)} detail</h3><span class="pill">${escapeHtml(abbrev)}</span></div>
        <div class="detail-list">
          ${teamDetailStats(local).join('')}
        </div>
      </aside>`;
  }

  function renderPlayers(rows, meta) {
    const teams = teamOptions();
    const statKeys = playerStatKeys();
    if (!statKeys.includes(state.playerStat)) state.playerStat = statKeys[0];
    $('#view-content').innerHTML = `
      <div class="section-head">
        <h2>${state.league.toUpperCase()} player leaders</h2>
        <div class="control-row">
          ${state.league === 'mlb' ? `<label class="small-label">Group <select id="player-group"><option value="hitting" ${state.playerGroup === 'hitting' ? 'selected' : ''}>Hitting</option><option value="pitching" ${state.playerGroup === 'pitching' ? 'selected' : ''}>Pitching</option></select></label>` : ''}
          <label class="small-label">Stat <select id="player-stat">${statKeys.map((key) => `<option value="${key}" ${key === state.playerStat ? 'selected' : ''}>${title(key)}</option>`).join('')}</select></label>
          <label class="small-label">Team <select id="player-team"><option value="">All teams</option>${teams}</select></label>
        </div>
      </div>
      ${nbaCoverageMarkup(meta)}
      ${rows.length ? playerTable(sortRows(rows, state.playerStat, 'desc')) : emptyMarkup('No player leaders available', 'The endpoint may still be landing, or no players match this filter.')}`;
    const group = $('#player-group');
    if (group) group.addEventListener('change', (e) => {
      state.playerGroup = e.target.value;
      state.playerStat = playerStatKeys()[0];
      state.cache = {};
      loadView(true);
    });
    $('#player-stat').addEventListener('change', (e) => {
      state.playerStat = e.target.value;
      state.cache = {};
      loadView(true);
    });
    $('#player-team').addEventListener('change', (e) => {
      state.playerTeam = e.target.value;
      state.cache = {};
      loadView(true);
    });
  }

  function renderSchedule(rows, meta) {
    $('#view-content').innerHTML = `
      <div class="section-head">
        <div><h2>${state.league.toUpperCase()} schedule</h2><p class="honesty">${state.league === 'mlb' ? 'Today’s MLB games include scheduled, in-progress, and final statuses; doubleheaders are listed as separate games.' : 'Schedules use the league endpoint directly; missing scores or dates are left blank rather than inferred.'}</p></div>
        <div class="control-row">
          ${state.league === 'nfl'
            ? `<label class="small-label">Week <select id="schedule-week"><option value="">Current/default</option>${Array.from({ length: 22 }, (_, i) => `<option value="${i + 1}" ${String(i + 1) === String(state.scheduleWeek) ? 'selected' : ''}>Week ${i + 1}</option>`).join('')}</select></label>`
            : `<label class="small-label">Date <input id="schedule-date" type="date" value="${escapeAttr(state.scheduleDate)}"></label>`}
        </div>
      </div>
      ${nbaCoverageMarkup(meta)}
      ${rows.length ? scheduleTable(rows) : emptyMarkup('No scheduled games available', 'It may be offseason, this date/week may be empty, or the backend may still be landing.')}`;
    const week = $('#schedule-week');
    if (week) week.addEventListener('change', (e) => { state.scheduleWeek = e.target.value; state.cache = {}; loadView(true); });
    const date = $('#schedule-date');
    if (date) date.addEventListener('change', (e) => { state.scheduleDate = e.target.value; state.cache = {}; loadView(true); });
  }

  function scheduleTable(rows) {
    return `<div class="table-wrap"><table><caption class="sr-only">${state.league.toUpperCase()} schedule</caption><thead><tr><th>Date</th><th>Away</th><th>Home</th><th>Status</th><th>Score</th></tr></thead><tbody>${rows.map((gameRow) => `<tr><td>${value(gameRow.game_date || gameRow.date || gameRow.start_time)}</td><td>${value(gameRow.away || gameRow.away_team || gameRow.away_abbrev)}</td><td>${value(gameRow.home || gameRow.home_team || gameRow.home_abbrev)}</td><td>${value(gameRow.status || gameRow.game_state)}</td><td>${value(gameRow.score || scoreText(gameRow))}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function scoreText(gameRow) {
    const away = gameRow.away_score ?? gameRow.visitor_score;
    const home = gameRow.home_score;
    return away == null || home == null ? '' : `${away}-${home}`;
  }

  function renderPredictions(rows, meta) {
    const teams = state.teams.length ? state.teams : sample[state.league].standings;
    $('#view-content').innerHTML = `
      <div class="section-head">
        <div><h2>${state.league.toUpperCase()} predictions</h2><p class="honesty">${honestyText(state.league)}</p></div>
      </div>
      ${nbaCoverageMarkup(meta)}
      ${meta && meta.prediction_notice ? `<div class="coverage-note" role="note"><strong>Prediction feed unavailable:</strong> ${escapeHtml(meta.prediction_notice)} The matchup picker below will also report if the model has not landed.</div>` : ''}
      <form id="matchup-form" class="matchup-form">
        <label class="small-label">Home team <select id="home-team" required>${teamSelectOptions(teams)}</select></label>
        <label class="small-label">Away team <select id="away-team" required>${teamSelectOptions(teams, 1)}</select></label>
        <button class="primary-btn" type="submit">Estimate matchup</button>
      </form>
      <div id="matchup-result"></div>
      <h3>Upcoming games</h3>
      ${rows.length ? `<div class="cards-grid">${rows.map(predictionCard).join('')}</div>` : emptyMarkup('No upcoming games listed', 'It is offseason/preseason or the schedule endpoint has no fixtures. Use the matchup picker above for an ad-hoc estimate.')}`;
    $('#matchup-form').addEventListener('submit', onMatchup);
  }

  async function onMatchup(event) {
    event.preventDefault();
    const home = $('#home-team').value;
    const away = $('#away-team').value;
    const target = $('#matchup-result');
    if (home === away) {
      target.innerHTML = emptyMarkup('Choose two different teams', 'Home and away teams must be different for a matchup estimate.');
      return;
    }
    target.innerHTML = loadingMarkup(2);
    try {
      const env = state.mock ? { ok: true, data: prediction(state.league, home, away, .55, mockAccuracy(state.league)), meta: { fetched_at: new Date().toISOString(), season_state: state.league === 'mlb' ? 'regular' : 'offseason', season: state.league === 'nba' ? '2025-26' : state.league === 'mlb' ? '2026' : '2025', stale: false, season_coverage: state.league === 'nba' ? { historical_game_logs: '2001-02 through 2022-23', current_standings: { seasons: [{ season: '2023-24' }, { season: '2024-25' }, { season: '2025-26' }] } } : null } } : await fetchEnvelope(endpoints.matchup(state.league, home, away), 'matchup prediction');
      handleMeta(env.meta);
      const cards = Array.isArray(env.data) ? env.data.map(normalizeObject) : [normalizeObject(env.data)];
      target.innerHTML = `<div class="cards-grid">${cards.map(predictionCard).join('')}</div>`;
    } catch (error) {
      target.innerHTML = emptyMarkup('Matchup estimate unavailable', error.message);
    }
  }

  function predictionCard(game) {
    const homeProb = asNumber(game.home_win_prob);
    const awayProb = asNumber(game.away_win_prob);
    return `
      <article class="prediction-card">
        <div class="section-head"><h3>${escapeHtml(game.away || 'Away')} at ${escapeHtml(game.home || 'Home')}</h3><span class="pill">${escapeHtml(game.game_date || 'Date TBD')}</span></div>
        <div class="probability" aria-label="Home win probability ${pct(homeProb)}">
          <strong>${escapeHtml(game.home || 'Home')} ${pct(homeProb)} · ${escapeHtml(game.away || 'Away')} ${pct(awayProb)}</strong>
          <div class="prob-track" role="img" aria-label="Probability bar showing ${pct(homeProb)} for home team"><div class="prob-fill" style="--prob:${Math.round((homeProb || 0) * 100)}%"></div></div>
        </div>
        <p class="honesty">${predictionHonesty(game)}</p>
      </article>`;
  }

  function playerTable(rows) {
    return `<div class="table-wrap"><table><thead><tr><th>Player</th><th>Team</th><th>Pos</th><th>Games</th><th>${title(state.playerStat)}</th></tr></thead><tbody>${rows.map((p) => `<tr><td>${escapeHtml(p.player_name || p.name || 'Unknown')}</td><td>${escapeHtml(p.team_abbrev || p.team || '')}</td><td>${escapeHtml(p.position || '')}</td><td>${value(p.games || p.games_played)}</td><td><strong>${value(p[state.playerStat] == null ? p.value : p[state.playerStat])}</strong></td></tr>`).join('')}</tbody></table></div>`;
  }

  function normalizeRows(data, key) {
    if (Array.isArray(data)) return data.map(normalizeObject);
    if (!data || typeof data !== 'object') return [];
    const candidates = [data[key], data[state.playerGroup], data.items, data.rows, data.results, data.teams, data.players, data.predictions, data.games, data.schedule, data.standings, data.data];
    const found = candidates.find(Array.isArray);
    return found ? found.map(normalizeObject) : [];
  }

  function normalizeObject(obj) {
    return obj && typeof obj === 'object' ? { ...obj } : {};
  }

  function matchesSearch(item) {
    if (!state.search || state.view === 'players') return true;
    return [item.name, item.abbrev, item.team_id, item.home, item.away].filter(Boolean).join(' ').toLowerCase().includes(state.search);
  }

  function sortRows(rows, key, dir) {
    return [...rows].sort((a, b) => {
      const av = a[key] == null && key === state.playerStat && a.value != null ? a.value : a[key] == null ? '' : a[key];
      const bv = b[key] == null && key === state.playerStat && b.value != null ? b.value : b[key] == null ? '' : b[key];
      if (key === 'record') return dir === 'asc' ? (a.wins || 0) - (b.wins || 0) : (b.wins || 0) - (a.wins || 0);
      const result = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true });
      return dir === 'asc' ? result : -result;
    });
  }

  function groupRows(rows) {
    const groups = new Map();
    rows.forEach((row) => {
      const name = `${row.conference || 'Other'} · ${row.division || 'Unassigned'}`;
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(row);
    });
    return [...groups.entries()];
  }

  function withGamesBehind(rows) {
    const leaders = new Map();
    rows.forEach((row) => {
      const group = `${row.conference || ''}|${row.division || ''}`;
      const current = leaders.get(group);
      if (!current || asNumber(row.win_pct) > asNumber(current.win_pct) || (asNumber(row.win_pct) === asNumber(current.win_pct) && asNumber(row.wins) > asNumber(current.wins))) {
        leaders.set(group, row);
      }
    });
    return rows.map((row) => {
      const group = `${row.conference || ''}|${row.division || ''}`;
      const leader = leaders.get(group) || row;
      const gb = row.games_behind ?? row.games_back ?? row.gb ?? ((asNumber(leader.wins) - asNumber(row.wins) + asNumber(row.losses) - asNumber(leader.losses)) / 2);
      return { ...row, games_behind: gb === 0 ? '—' : Number.isFinite(Number(gb)) ? Number(gb).toFixed(Number(gb) % 1 ? 1 : 0) : gb };
    });
  }

  function cell(team, key) {
    if (key === 'name') return `<div class="team-cell">${logo(team)}<div><strong>${escapeHtml(team.name || team.abbrev || '')}</strong><div class="abbr">${escapeHtml(team.abbrev || '')}</div></div></div>`;
    if (key === 'record') return record(team);
    if (key === 'win_pct' || key === 'points_pct') return pct(team[key]);
    if (key === 'differential') return `<span class="${classForDiff(team[key])}">${diff(team[key])}</span>`;
    if (key === 'streak') return `<span class="${classForStreak(team[key])}">${escapeHtml(team[key] || '—')}</span>`;
    if (key === 'otl') return value(state.league === 'nfl' ? team.ties : team.otl);
    return value(team[key]);
  }

  function teamOptions() {
    return state.teams.map((team) => `<option value="${escapeAttr(team.abbrev || team.team_id)}" ${(team.abbrev || team.team_id) === state.playerTeam ? 'selected' : ''}>${escapeHtml(team.name || team.abbrev)}</option>`).join('');
  }

  function playerStatKeys() {
    const config = leagueConfig[state.league];
    return config.playerGroups ? config.playerGroups[state.playerGroup] || config.playerStats : config.playerStats;
  }

  function teamSelectOptions(teams, selectedIndex) {
    return teams.map((team, index) => {
      const abbrev = team.abbrev || team.team_id || team.name;
      return `<option value="${escapeAttr(abbrev)}" ${index === selectedIndex ? 'selected' : ''}>${escapeHtml(team.name || abbrev)}</option>`;
    }).join('');
  }

  function showSkeleton() {
    $('#view-content').innerHTML = loadingMarkup(6);
  }
  function loadingMarkup(count) {
    return `<div class="skeleton" aria-label="Loading">${Array.from({ length: count }, () => '<div class="skeleton-line"></div>').join('')}</div>`;
  }
  function renderEmpty(titleText, body) {
    $('#view-content').innerHTML = emptyMarkup(titleText, body);
  }
  function emptyMarkup(titleText, body) {
    return `<div class="empty-state"><h2>${escapeHtml(titleText)}</h2><p>${escapeHtml(body)}</p></div>`;
  }
  function renderError(message) {
    $('#view-content').innerHTML = `${nbaCoverageMarkup({})}<div class="error-state"><h2>Could not load ${escapeHtml(title(state.view))}</h2><p>${escapeHtml(message)}</p><p>Auto-refresh will retry with backoff. Add <code>?mock=1</code> to the URL to preview the full UI with clearly labeled mock data.</p></div>`;
  }
  function setNotice(message, kind) {
    const notice = $('#notice');
    notice.className = `banner ${kind || 'neutral'}${message ? '' : ' hidden'}`;
    notice.textContent = message;
  }

  function logo(team) {
    return team.logo_url ? `<img class="logo" src="${escapeAttr(team.logo_url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : `<span class="logo" aria-hidden="true"></span>`;
  }
  function record(team) {
    const extra = state.league === 'nhl' ? team.otl : state.league === 'nfl' ? team.ties : null;
    return `${num(team.wins)}-${num(team.losses)}${extra == null || extra === '' ? '' : `-${num(extra)}`}`;
  }
  function statBox(label, val) {
    return `<div class="stat-box"><span>${escapeHtml(label)}</span><strong>${val == null || val === '' ? '—' : val}</strong></div>`;
  }
  function pct(valueIn) {
    const n = asNumber(valueIn);
    return n == null ? '—' : `${(n * 100).toFixed(n < .1 ? 2 : 1)}%`;
  }
  function diff(valueIn) {
    const n = asNumber(valueIn);
    if (n == null) return '—';
    return `${n > 0 ? '+' : ''}${n}`;
  }
  function value(v) {
    return v == null || v === '' ? '—' : escapeHtml(String(v));
  }
  function num(v) {
    return v == null ? '—' : v;
  }
  function asNumber(v) {
    if (v == null || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function classForDiff(v) {
    const n = asNumber(v);
    return n == null || n === 0 ? 'even' : n > 0 ? 'pos' : 'neg';
  }
  function classForStreak(v) {
    return String(v || '').startsWith('W') ? 'pill pos' : String(v || '').startsWith('L') ? 'pill neg' : 'pill even';
  }
  function title(s) {
    return String(s || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }
  function formatDateTime(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? 'unknown time' : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  }
  function todayInputDate() {
    const d = new Date();
    const offset = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - offset).toISOString().slice(0, 10);
  }
  function seasonStateText(meta, stateName) {
    const season = formatSeason(meta.season);
    if (stateName === 'offseason') return `${season} season complete, showing final standings and completed-season data.`;
    if (stateName === 'preseason') return `${season} preseason has not started; showing available preseason or prior data, not a live regular-season table.`;
    return `${season} season is ${stateName}; showing ${stateName} data, not a live regular-season table.`;
  }
  function formatSeason(season) {
    const s = String(season || 'Current');
    if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(6)}`;
    return s;
  }
  function predictionHonesty(game) {
    const league = game.league || state.league;
    const disclaimer = escapeHtml(game.disclaimer || honestyText(league));
    if (asNumber(game.model_accuracy) == null || asNumber(game.baseline_accuracy) == null) {
      return `<strong>Measured accuracy:</strong> unavailable from this response. ${disclaimer} Not betting advice.`;
    }
    return `<strong>Measured accuracy:</strong> model ${pct(game.model_accuracy)} vs baseline ${pct(game.baseline_accuracy)}. ${disclaimer} Not betting advice.`;
  }
  function honestyText(league) {
    if (league === 'nhl') return 'NHL model accuracy is 56.82% versus a 53.5% always-home baseline. These are modest statistical estimates, not guaranteed edges.';
    if (league === 'nfl') return 'NFL market-free accuracy is 66.11% and full-model accuracy is 67.40% versus a 68.51% Vegas bar; neither beats the market. Not betting advice.';
    if (league === 'mlb') return 'MLB predictions are shown only when the backend provides measured model accuracy and disclaimers. Not betting advice.';
    return 'NBA predictions are shown only when the backend provides measured model accuracy and disclaimers. Not betting advice.';
  }
  function mockAccuracy(league) {
    if (league === 'nhl') return [0.5682, 0.535, 'Model accuracy 56.82% vs 53.5% home baseline.'];
    if (league === 'nfl') return [0.6611, 0.6851, 'NFL market-free accuracy 66.11%; full 67.40%; Vegas bar 68.51%, so it does not beat the market.'];
    return [null, null, `${league.toUpperCase()} prediction model accuracy is not available in this mock fixture; wait for measured backend results before trusting probabilities.`];
  }
  function teamDetailStats(local) {
    const config = leagueConfig[state.league];
    const entries = [
      ['Conference', local.conference], ['Division', local.division], ['Games played', local.games_played],
      ['Record', record(local)], ['Win %', pct(local.win_pct)], [config.scoreFor, local.goals_for],
      [config.scoreAgainst, local.goals_against], ['Home record', local.home_record], ['Away record', local.away_record],
      ['Streak', local.streak], ['Last 10', local.last10], ['Differential', diff(local.differential)]
    ];
    if (state.league === 'nhl') entries.splice(5, 0, ['Points', local.points], ['Points %', pct(local.points_pct)]);
    return entries.map(([label, val]) => statBox(label, val));
  }
  function nbaCoverageMarkup(meta = {}) {
    if (state.league !== 'nba') return '';
    const text = nbaCoverageText(meta);
    return `<div class="coverage-note" role="note"><strong>NBA data coverage:</strong> ${escapeHtml(text)}</div>`;
  }
  function nbaCoverageText(meta = {}) {
    const coverage = meta.season_coverage || meta.coverage || meta.data_coverage || {};
    if (typeof coverage === 'string') return coverage;
    const historical = coverage.historical_game_logs || coverage.historical || coverage.history || summarizeSeasonCoverage(coverage.historical_games) || meta.historical_coverage || '2001-02 through 2022-23';
    const current = coverage.current_standings || coverage.current || coverage.current_season || meta.current_coverage || ['2023-24', '2024-25', '2025-26'];
    const currentText = summarizeSeasonCoverage(current);
    return `Historical game logs cover ${historical}; current standings are available for ${currentText}.`;
  }
  function summarizeSeasonCoverage(valueIn) {
    if (valueIn == null || valueIn === '') return '';
    if (typeof valueIn === 'string') return valueIn;
    const rawSeasons = Array.isArray(valueIn) ? valueIn : valueIn.seasons;
    if (!Array.isArray(rawSeasons)) return String(valueIn);
    const seasons = rawSeasons.map((item) => typeof item === 'string' ? item : item && item.season).filter(Boolean);
    if (!seasons.length) return '';
    if (seasons.length > 6) return `${seasons[0]} through ${seasons[seasons.length - 1]}`;
    return seasons.join(', ');
  }
  function escapeHtml(valueIn) {
    return String(valueIn == null ? '' : valueIn).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }
  function escapeAttr(valueIn) {
    return escapeHtml(valueIn).replace(/`/g, '&#96;');
  }
})();
