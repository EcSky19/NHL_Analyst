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
    failureCount: 0,
    timer: null,
    cache: {},
    teams: [],
    selectedTeam: null,
    playerStat: 'points',
    playerTeam: '',
    darkManual: localStorage.getItem('sports-ui-theme') || ''
  };

  const endpoints = {
    standings: (league) => `/api/${league}/standings`,
    teams: (league) => `/api/${league}/teams`,
    players: (league) => `/api/${league}/players?stat=${encodeURIComponent(state.playerStat)}&limit=50${state.playerTeam ? `&team=${encodeURIComponent(state.playerTeam)}` : ''}`,
    predictions: (league) => `/api/predictions/${league}`,
    matchup: (league, home, away) => `/api/predictions/matchup?league=${encodeURIComponent(league)}&home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`
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
    }
  };
  sample.nhl.teams = sample.nhl.standings;
  sample.nfl.teams = sample.nfl.standings;

  function row(abbrev, name, conference, division, rank, games, wins, losses, otl, ties, points, gf, ga, streak, last10) {
    return {
      team_id: abbrev, abbrev, name, conference, division, rank, games_played: games,
      wins, losses, otl, ties, points, points_pct: points ? points / (games * 2) : null,
      win_pct: wins / games, goals_for: gf, goals_against: ga, differential: gf - ga,
      streak, last10, home_record: '24-12-5', away_record: '22-15-4', logo_url: '', clinched: null
    };
  }
  function player(name, team, position, games, goals, assists, points) {
    return { name, player_name: name, team, team_abbrev: team, position, games, games_played: games, goals, assists, points, touchdowns: goals, passing_tds: goals, passing_yards: points * 10, fantasy_points: points };
  }

  function mockEnvelope(key) {
    const league = state.league;
    const data = key === 'predictions'
      ? samplePredictions(league)
      : sample[league][key];
    return Promise.resolve({
      ok: true,
      data,
      meta: { source: 'mock-fixture', fetched_at: new Date().toISOString(), cached: false, stale: false, season: league === 'nhl' ? '20252026' : '2025', season_state: 'offseason' }
    });
  }

  function samplePredictions(league) {
    const teams = sample[league].standings;
    const acc = league === 'nhl' ? [0.5682, 0.535, 'Model accuracy 56.82% vs 53.5% always-home baseline.'] : [0.6611, 0.6851, 'NFL market-free accuracy 66.11%; full 67.40%; Vegas bar 68.51%, so it does not beat the market.'];
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
      state.playerStat = state.league === 'nfl' ? 'passing_yards' : 'points';
      state.playerTeam = '';
      state.selectedTeam = null;
      state.teams = [];
      state.cache = {};
      updateActive();
      loadView(true);
    }));
    document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => {
      state.view = button.dataset.view;
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
    const base = state.view === 'standings' ? 60000 : 120000;
    const delay = Math.min(base * Math.max(1, 2 ** Math.min(state.failureCount, 4)), 15 * 60000);
    state.timer = setTimeout(() => loadView(), delay);
  }

  function updatePollState() {
    const text = state.paused ? 'Auto-refresh paused' : document.hidden ? 'Auto-refresh paused while tab is hidden' : state.failureCount ? `Backoff active after ${state.failureCount} failed refresh${state.failureCount > 1 ? 'es' : ''}` : 'Auto-refresh active';
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
    const cacheKey = `${key}:${state.league}:${state.playerStat}:${state.playerTeam}`;
    if (!force && state.cache[cacheKey]) return state.cache[cacheKey];
    let envelope;
    if (state.mock) {
      envelope = await mockEnvelope(key);
    } else {
      envelope = await fetchEnvelope(endpoints[key](state.league), key);
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
    $('#season-banner').classList.toggle('hidden', !nonRegular);
    $('#season-banner').textContent = nonRegular ? `${formatSeason(meta.season)} season is ${stateName}; showing ${stateName === 'offseason' ? 'final' : stateName} data, not a live regular-season table.` : '';
  }

  function renderFromCache() {
    const keys = Object.keys(state.cache).filter((key) => key.startsWith(`${state.view}:${state.league}`));
    if (keys.length) render(state.view, state.cache[keys[0]]);
  }

  function render(view, envelope) {
    const rows = normalizeRows(envelope.data, view).filter(matchesSearch);
    if (view === 'standings') renderStandings(rows);
    if (view === 'teams') renderTeams(rows);
    if (view === 'players') renderPlayers(rows);
    if (view === 'predictions') renderPredictions(rows);
  }

  function renderStandings(rows) {
    const content = $('#view-content');
    const columns = [
      ['rank', 'Rank'], ['name', 'Team'], ['games_played', 'GP'], ['wins', 'W'], ['losses', 'L'], ['otl', state.league === 'nhl' ? 'OTL' : 'T'], ['points', state.league === 'nhl' ? 'Pts' : 'Pts'], ['win_pct', 'Win %'], ['goals_for', state.league === 'nhl' ? 'GF' : 'PF'], ['goals_against', state.league === 'nhl' ? 'GA' : 'PA'], ['differential', 'Diff'], ['streak', 'Streak'], ['last10', 'Last 10']
    ];
    if (!rows.length) return renderEmpty('No standings available', 'There are no rows for this search or the backend has no data yet.');
    const sorted = sortRows(rows, state.sort.key, state.sort.dir);
    const grouped = state.groupStandings ? groupRows(sorted) : [['League-wide table', sorted]];
    content.innerHTML = `
      <div class="section-head">
        <div><h2>${state.league.toUpperCase()} standings</h2><p class="honesty">One shared standings table handles NHL and NFL because both use the contract's common row shape.</p></div>
        <button id="group-toggle" class="ghost-btn" type="button" aria-pressed="${state.groupStandings}">${state.groupStandings ? 'Show league-wide table' : 'Group by conference/division'}</button>
      </div>
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
      renderStandings(rows);
    }));
    $('#group-toggle').addEventListener('click', () => {
      state.groupStandings = !state.groupStandings;
      renderStandings(rows);
    });
  }

  function renderTeams(rows) {
    if (!rows.length) return renderEmpty('No team stats available', 'Try clearing the team search or refreshing once routers are live.');
    $('#view-content').innerHTML = `
      <div class="section-head"><h2>${state.league.toUpperCase()} team stats</h2><p class="honesty">Select a card for detail. Missing fields are shown as unavailable rather than guessed.</p></div>
      <div class="cards-grid">${rows.map((team) => `
        <button class="team-card" type="button" data-team="${escapeAttr(team.abbrev || team.team_id || team.name)}">
          <div class="team-cell">${logo(team)}<div><strong>${escapeHtml(team.name || team.abbrev || 'Unknown team')}</strong><div class="abbr">${escapeHtml(team.abbrev || team.team_id || '')}</div></div></div>
          <div class="stat-grid">
            ${statBox('Record', `${num(team.wins)}-${num(team.losses)}${team.otl || team.ties ? `-${num(team.otl || team.ties)}` : ''}`)}
            ${statBox('Win %', pct(team.win_pct))}
            ${statBox(state.league === 'nhl' ? 'Goals for' : 'Points for', team.goals_for)}
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
          ${['conference', 'division', 'games_played', 'wins', 'losses', 'points', 'points_pct', 'home_record', 'away_record', 'streak', 'last10', 'differential'].map((key) => statBox(title(key), key.includes('pct') ? pct(local[key]) : (key === 'differential' ? diff(local[key]) : value(local[key])))).join('')}
        </div>
      </aside>`;
  }

  function renderPlayers(rows) {
    const teams = teamOptions();
    const statKeys = state.league === 'nhl' ? ['points', 'goals', 'assists', 'plus_minus', 'shots'] : ['passing_yards', 'passing_tds', 'interceptions', 'rushing_yards', 'fantasy_points'];
    if (!statKeys.includes(state.playerStat)) state.playerStat = statKeys[0];
    $('#view-content').innerHTML = `
      <div class="section-head">
        <h2>${state.league.toUpperCase()} player leaders</h2>
        <div class="control-row">
          <label class="small-label">Stat <select id="player-stat">${statKeys.map((key) => `<option value="${key}" ${key === state.playerStat ? 'selected' : ''}>${title(key)}</option>`).join('')}</select></label>
          <label class="small-label">Team <select id="player-team"><option value="">All teams</option>${teams}</select></label>
        </div>
      </div>
      ${rows.length ? playerTable(sortRows(rows, state.playerStat, 'desc')) : emptyMarkup('No player leaders available', 'The endpoint may still be landing, or no players match this filter.')}`;
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

  function renderPredictions(rows) {
    const teams = state.teams.length ? state.teams : sample[state.league].standings;
    $('#view-content').innerHTML = `
      <div class="section-head">
        <div><h2>${state.league.toUpperCase()} predictions</h2><p class="honesty">${honestyText(state.league)}</p></div>
      </div>
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
      const env = state.mock ? { ok: true, data: prediction(state.league, home, away, .55, state.league === 'nhl' ? [0.5682, 0.535, 'Model accuracy 56.82% vs 53.5% home baseline.'] : [0.6611, 0.6851, 'NFL market-free accuracy 66.11%; full 67.40%; Vegas bar 68.51%, so it does not beat the market.']), meta: { fetched_at: new Date().toISOString(), season_state: 'offseason', season: '2025', stale: false } } : await fetchEnvelope(endpoints.matchup(state.league, home, away), 'matchup prediction');
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
        <p class="honesty"><strong>Measured accuracy:</strong> model ${pct(game.model_accuracy)} vs baseline ${pct(game.baseline_accuracy)}. ${escapeHtml(game.disclaimer || honestyText(game.league || state.league))} Not betting advice.</p>
      </article>`;
  }

  function playerTable(rows) {
    return `<div class="table-wrap"><table><thead><tr><th>Player</th><th>Team</th><th>Pos</th><th>Games</th><th>${title(state.playerStat)}</th></tr></thead><tbody>${rows.map((p) => `<tr><td>${escapeHtml(p.player_name || p.name || 'Unknown')}</td><td>${escapeHtml(p.team_abbrev || p.team || '')}</td><td>${escapeHtml(p.position || '')}</td><td>${value(p.games || p.games_played)}</td><td><strong>${value(p[state.playerStat] == null ? p.value : p[state.playerStat])}</strong></td></tr>`).join('')}</tbody></table></div>`;
  }

  function normalizeRows(data, key) {
    if (Array.isArray(data)) return data.map(normalizeObject);
    if (!data || typeof data !== 'object') return [];
    const candidates = [data[key], data.items, data.rows, data.results, data.teams, data.players, data.predictions, data.games, data.standings, data.data];
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
      const av = a[key] == null ? '' : a[key];
      const bv = b[key] == null ? '' : b[key];
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

  function cell(team, key) {
    if (key === 'name') return `<div class="team-cell">${logo(team)}<div><strong>${escapeHtml(team.name || team.abbrev || '')}</strong><div class="abbr">${escapeHtml(team.abbrev || '')}</div></div></div>`;
    if (key === 'win_pct' || key === 'points_pct') return pct(team[key]);
    if (key === 'differential') return `<span class="${classForDiff(team[key])}">${diff(team[key])}</span>`;
    if (key === 'streak') return `<span class="${classForStreak(team[key])}">${escapeHtml(team[key] || '—')}</span>`;
    if (key === 'otl') return value(state.league === 'nfl' ? team.ties : team.otl);
    return value(team[key]);
  }

  function teamOptions() {
    return state.teams.map((team) => `<option value="${escapeAttr(team.abbrev || team.team_id)}" ${(team.abbrev || team.team_id) === state.playerTeam ? 'selected' : ''}>${escapeHtml(team.name || team.abbrev)}</option>`).join('');
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
    $('#view-content').innerHTML = `<div class="error-state"><h2>Could not load ${escapeHtml(title(state.view))}</h2><p>${escapeHtml(message)}</p><p>Auto-refresh will retry with backoff. Add <code>?mock=1</code> to the URL to preview the full UI with clearly labeled mock data.</p></div>`;
  }
  function setNotice(message, kind) {
    const notice = $('#notice');
    notice.className = `banner ${kind || 'neutral'}${message ? '' : ' hidden'}`;
    notice.textContent = message;
  }

  function logo(team) {
    return team.logo_url ? `<img class="logo" src="${escapeAttr(team.logo_url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : `<span class="logo" aria-hidden="true"></span>`;
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
    return String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }
  function formatDateTime(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? 'unknown time' : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  }
  function formatSeason(season) {
    const s = String(season || 'Current');
    if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(6)}`;
    return s;
  }
  function honestyText(league) {
    return league === 'nhl'
      ? 'NHL model accuracy is 56.82% versus a 53.5% always-home baseline. These are modest statistical estimates, not guaranteed edges.'
      : 'NFL market-free accuracy is 66.11% and full-model accuracy is 67.40% versus a 68.51% Vegas bar; neither beats the market. Not betting advice.';
  }
  function escapeHtml(valueIn) {
    return String(valueIn == null ? '' : valueIn).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }
  function escapeAttr(valueIn) {
    return escapeHtml(valueIn).replace(/`/g, '&#96;');
  }
})();
