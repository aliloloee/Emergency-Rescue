/*
 * The administrator's system-wide view.
 *
 * Read only by design: this page sends nothing, because dispatching belongs to
 * the centre that owns the agent. RootPanelConsumer has no receive() at all,
 * so there is nothing here to send to.
 *
 * Self-contained rather than built on main.js, which assumes a single region
 * and a dispatch panel beside it.
 */
(function () {
  "use strict";

  var MISSION = { JUST_DEFINED: 1, IN_PROGRESS: 2, REPORTED: 3, CLOSED: 4 };
  var ALERT = { UNROUTED: 1, ROUTED: 2 };

  var MISSION_LABEL = {
    1: { text: "Awaiting ack", cls: "badge--waiting" },
    2: { text: "In progress", cls: "badge--progress" },
    3: { text: "Reported", cls: "badge--reported" },
    4: { text: "Closed", cls: "badge--closed" },
  };

  var OUTCOME_LABEL = {
    1: { text: "Success", cls: "outcome--success" },
    2: { text: "Failure", cls: "outcome--failure" },
    3: { text: "Aborted", cls: "outcome--aborted" },
  };

  var state = {
    centres: [],
    agents: [],
    subjects: [],
    alerts: {},
    missions: {},
  };

  var wsBase =
    (window.location.protocol === "https:" ? "wss" : "ws") +
    "://" +
    window.location.host;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  // -------------------------------------------------------------------- map --

  var map = L.map("root-map").setView([centerLat, centerLng], 12);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  var icons = {
    0: L.icon({
      iconUrl: subjectIconSrc,
      iconSize: [34, 34],
      iconAnchor: [17, 34],
      popupAnchor: [0, -30],
    }),
    1: L.icon({
      iconUrl: agentIconSrc,
      iconSize: [34, 34],
      iconAnchor: [17, 34],
      popupAnchor: [0, -30],
    }),
  };

  var markers = {};

  function place(kind, pk, lat, lng, label) {
    if (lat === null || lat === undefined) {
      return;
    }
    var id = kind + "-" + pk;
    if (markers[id]) {
      markers[id].setLatLng([lat, lng]);
    } else {
      markers[id] = L.marker([lat, lng], { icon: icons[kind] }).addTo(map);
    }
    markers[id].bindPopup(label);
  }

  // ------------------------------------------------------------- rendering --

  function openMissions() {
    return Object.keys(state.missions)
      .map(function (id) {
        return state.missions[id];
      })
      .filter(function (m) {
        return m.status !== MISSION.CLOSED;
      });
  }

  function closedMissions() {
    return Object.keys(state.missions)
      .map(function (id) {
        return state.missions[id];
      })
      .filter(function (m) {
        return m.status === MISSION.CLOSED;
      })
      .sort(function (a, b) {
        return b.id - a.id;
      });
  }

  function openAlerts() {
    return Object.keys(state.alerts)
      .map(function (id) {
        return state.alerts[id];
      })
      .filter(function (a) {
        return a.status === ALERT.UNROUTED || a.status === ALERT.ROUTED;
      });
  }

  function renderTiles() {
    var free = state.agents.filter(function (a) {
      return !a.busy;
    }).length;

    document.getElementById("t-centres").textContent = state.centres.length;
    document.getElementById("t-agents").textContent =
      free + " / " + state.agents.length;
    document.getElementById("t-subjects").textContent = openAlerts().length;
    document.getElementById("t-open").textContent = openMissions().length;
    document.getElementById("t-closed").textContent = closedMissions().length;
  }

  function renderUnrouted() {
    var stranded = openAlerts().filter(function (a) {
      return a.status === ALERT.UNROUTED;
    });

    var banner = document.getElementById("unrouted");
    banner.hidden = stranded.length === 0;
    if (!stranded.length) {
      return;
    }

    document.getElementById("unrouted-title").textContent =
      stranded.length === 1
        ? "1 alert has nobody to go to"
        : stranded.length + " alerts have nobody to go to";

    document.getElementById("unrouted-text").textContent =
      stranded
        .map(function (a) {
          return a.subject_device_name;
        })
        .join(", ") +
      " — no agent was free anywhere when these were raised, so no centre has " +
      "been told. They route themselves as soon as one frees up.";
  }

  function renderCentres() {
    var list = document.getElementById("centres");
    list.textContent = "";

    state.centres.forEach(function (centre) {
      var mine = state.agents.filter(function (a) {
        return a.center_id === centre.id;
      });
      var free = mine.filter(function (a) {
        return !a.busy;
      }).length;
      var busy = mine.length - free;

      var row = el("li", "row");
      var top = el("div", "row__top");
      top.appendChild(el("span", "row__name", centre.name));
      top.appendChild(el("span", "row__free", free + " free"));
      row.appendChild(top);

      row.appendChild(
        el(
          "div",
          "row__meta",
          (centre.region || "no region") +
            " · " +
            mine.length +
            (mine.length === 1 ? " agent" : " agents") +
            (busy ? " · " + busy + " on a mission" : "")
        )
      );
      list.appendChild(row);
    });
  }

  function renderMissions() {
    var body = document.getElementById("mission-rows");
    body.textContent = "";

    var rows = openMissions()
      .sort(function (a, b) {
        return b.id - a.id;
      })
      .concat(closedMissions());

    if (!rows.length) {
      var empty = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = 6;
      cell.className = "empty";
      cell.textContent = "No mission has been created yet.";
      empty.appendChild(cell);
      body.appendChild(empty);
      return;
    }

    rows.forEach(function (mission) {
      var tr = document.createElement("tr");

      var id = el("td", null, String(mission.id));
      id.style.fontWeight = "600";
      tr.appendChild(id);

      tr.appendChild(el("td", null, mission.center || "—"));
      tr.appendChild(el("td", null, mission.agent_name));
      tr.appendChild(el("td", null, "device " + mission.subject_device_id));

      var statusCell = document.createElement("td");
      var label = MISSION_LABEL[mission.status];
      statusCell.appendChild(el("span", "badge " + label.cls, label.text));
      tr.appendChild(statusCell);

      var outcomeCell = document.createElement("td");
      var outcome = OUTCOME_LABEL[mission.outcome];
      if (outcome) {
        outcomeCell.appendChild(el("span", outcome.cls, outcome.text));
      } else {
        outcomeCell.className = "muted";
        outcomeCell.textContent = "—";
      }
      tr.appendChild(outcomeCell);

      body.appendChild(tr);
    });
  }

  function render() {
    renderTiles();
    renderUnrouted();
    renderCentres();
    renderMissions();
  }

  // ---------------------------------------------------------------- socket --

  var statusEl = document.getElementById("root-status");

  function setStatus(live) {
    statusEl.className = "status status--" + (live ? "live" : "down");
    statusEl.querySelector(".status__text").textContent = live
      ? "Live"
      : "Reconnecting…";
  }

  function applySnapshot(snapshot) {
    state.centres = snapshot.centers;
    state.agents = snapshot.agents;
    state.subjects = snapshot.subject_devices;

    snapshot.alerts.forEach(function (alert) {
      state.alerts[alert.id] = alert;
    });
    snapshot.open_missions.concat(snapshot.closed_missions).forEach(function (m) {
      state.missions[m.id] = m;
    });

    state.agents.forEach(function (agent) {
      place(1, agent.id, agent.lat, agent.lng, agent.name + " · " + agent.center);
    });
    state.subjects.forEach(function (device) {
      place(0, device.id, device.lat, device.lng, device.name);
    });
  }

  function refreshToken() {
    return fetch(refreshTokenUrl, { method: "POST", credentials: "same-origin" })
      .then(function (response) {
        return response.ok;
      })
      .catch(function () {
        return false;
      });
  }

  function open() {
    var socket = new WebSocket(wsBase + "/" + rootPanelWS);

    socket.onopen = function () {
      setStatus(true);
    };

    socket.onmessage = function (event) {
      var message = JSON.parse(event.data);

      if (message.snapshot) {
        applySnapshot(message.snapshot);
      }
      if (message.alert) {
        state.alerts[message.alert.id] = message.alert;
      }
      if (message.mission) {
        state.missions[message.mission.id] = message.mission;
      }
      if (message.device_data) {
        var d = message.device_data;
        place(
          d.type,
          d.pk,
          d.lat,
          d.lng,
          d.type === 0
            ? "Subject device " + d.pk + " · " + d.heartrate + " bpm"
            : "Agent device " + d.pk
        );
      }

      render();
    };

    socket.onclose = function (event) {
      setStatus(false);

      if (event.code === 4001) {
        refreshToken().then(function (ok) {
          if (ok) {
            open();
          } else {
            window.location.href = logoutUrl;
          }
        });
        return;
      }

      if (event.code === 4005) {
        // A new token cannot make this account a root account.
        statusEl.querySelector(".status__text").textContent = "Not permitted";
        return;
      }

      window.setTimeout(open, 3000);
    };
  }

  render();
  open();
})();
