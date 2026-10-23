/*
 * The emergency centre's dispatch panel.
 *
 * Talks to CenterPanelConsumer over ws/center/panel/. Everything the operator
 * can do goes out of this file; everything they see comes in through it.
 *
 * Nothing here decides anything: the server owns the rules, and a refused
 * request comes back as an error with a code. The panel's job is to make the
 * decision legible and hard to get wrong.
 */
(function () {
  "use strict";

  // Mirrors settings/base.py. Changing them there means changing them here.
  var ALERT = { UNROUTED: 1, ROUTED: 2, CONVERTED: 3, DISMISSED: 4 };
  var MISSION = { JUST_DEFINED: 1, IN_PROGRESS: 2, REPORTED: 3, CLOSED: 4 };
  var OUTCOME = { SUCCESS: 1, FAILURE: 2, ABORTED: 3 };

  var MISSION_LABEL = {
    1: { text: "Awaiting acknowledgement", cls: "badge--waiting" },
    2: { text: "In progress", cls: "badge--progress" },
    3: { text: "Reported", cls: "badge--reported" },
    4: { text: "Closed", cls: "badge--closed" },
  };

  var OUTCOME_LABEL = { 1: "Success", 2: "Failure", 3: "Aborted" };

  var state = {
    alerts: {},
    missions: {},
    roster: [],
    ranked: [],
    rankedFor: null,
    selectedAlert: null,
    selectedAgent: null,
    error: null,
  };

  var nodes = {
    alerts: document.getElementById("alerts"),
    alertCount: document.getElementById("alert-count"),
    agents: document.getElementById("agents"),
    agentsLabel: document.getElementById("agents-label"),
    actions: document.getElementById("alert-actions"),
    dispatch: document.getElementById("dispatch"),
    dismiss: document.getElementById("dismiss"),
    missions: document.getElementById("missions"),
    missionCount: document.getElementById("mission-count"),
    error: document.getElementById("panel-error"),
  };

  // ------------------------------------------------------------- helpers --

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

  function clockOf(iso) {
    if (!iso) {
      return "";
    }
    var when = new Date(iso);
    return when.toLocaleTimeString([], { hour12: false });
  }

  function agoOf(iso) {
    if (!iso) {
      return "";
    }
    var seconds = Math.max(0, Math.round((Date.now() - new Date(iso)) / 1000));
    if (seconds < 60) {
      return seconds + "s ago";
    }
    return Math.round(seconds / 60) + " min ago";
  }

  function farOf(metres) {
    if (metres === null || metres === undefined) {
      return "";
    }
    return metres < 1000 ? metres + " m" : (metres / 1000).toFixed(1) + " km";
  }

  function openAlerts() {
    return Object.keys(state.alerts)
      .map(function (id) {
        return state.alerts[id];
      })
      .filter(function (alert) {
        return alert.status === ALERT.UNROUTED || alert.status === ALERT.ROUTED;
      })
      .sort(function (a, b) {
        return new Date(a.first_seen) - new Date(b.first_seen);
      });
  }

  function openMissions() {
    return Object.keys(state.missions)
      .map(function (id) {
        return state.missions[id];
      })
      .filter(function (mission) {
        return mission.status !== MISSION.CLOSED;
      })
      .sort(function (a, b) {
        return a.id - b.id;
      });
  }

  // ------------------------------------------------------------ rendering --

  function renderError() {
    nodes.error.textContent = "";
    if (!state.error) {
      nodes.error.hidden = true;
      return;
    }
    nodes.error.hidden = false;
    nodes.error.appendChild(document.createTextNode(state.error));
  }

  function renderAlerts() {
    var alerts = openAlerts();
    nodes.alerts.textContent = "";
    nodes.alertCount.textContent = alerts.length;
    nodes.alertCount.className = alerts.length ? "count count--urgent" : "count";

    if (!alerts.length) {
      // A subject already being rescued keeps transmitting but raises nothing,
      // so "no subject is transmitting" would be a lie while a mission runs.
      nodes.alerts.appendChild(
        el(
          "p",
          "empty",
          openMissions().length
            ? "No new alerts. A rescue is already under way."
            : "No subject is transmitting."
        )
      );
      return;
    }

    alerts.forEach(function (alert) {
      var card = el("button", "alert");
      card.type = "button";
      card.setAttribute("aria-pressed", String(state.selectedAlert === alert.id));

      var top = el("span", "alert__top");
      top.appendChild(el("span", "alert__name", alert.subject_device_name));
      top.appendChild(el("span", "alert__time", clockOf(alert.first_seen)));
      card.appendChild(top);

      card.appendChild(
        el(
          "span",
          "alert__where",
          alert.lat.toFixed(5) + ", " + alert.lng.toFixed(5)
        )
      );

      if (alert.heartrate !== null && alert.heartrate !== undefined) {
        card.appendChild(el("span", "chip chip--bpm", alert.heartrate + " bpm"));
      }

      if (alert.status === ALERT.UNROUTED) {
        card.appendChild(
          el("span", "hint", "No agent was free when this was raised.")
        );
      }

      card.addEventListener("click", function () {
        selectAlert(alert.id);
      });

      nodes.alerts.appendChild(card);
    });
  }

  function renderAgents() {
    nodes.agents.textContent = "";

    var selected = state.selectedAlert;
    var ranked = selected !== null && state.rankedFor === selected;
    var list = ranked ? state.ranked : state.roster;

    nodes.agentsLabel.textContent = ranked
      ? "Your agents, nearest first"
      : "Your agents, free";

    if (!list.length) {
      nodes.agents.appendChild(
        el("li", "empty", "None of your agents is free.")
      );
      return;
    }

    list.forEach(function (agent) {
      var item = document.createElement("li");
      var button = el("button", "agent");
      button.type = "button";
      button.setAttribute(
        "aria-pressed",
        String(state.selectedAgent === agent.id)
      );

      button.appendChild(el("span", "agent__swatch"));
      button.appendChild(el("span", "agent__name", agent.name));
      if (ranked) {
        button.appendChild(el("span", "agent__far", farOf(agent.distance_m)));
      }

      button.addEventListener("click", function () {
        state.selectedAgent = agent.id;
        render();
      });

      item.appendChild(button);
      nodes.agents.appendChild(item);
    });
  }

  function renderActions() {
    var alert = state.selectedAlert !== null ? state.alerts[state.selectedAlert] : null;
    var ready = Boolean(alert) && state.selectedAgent !== null;

    nodes.actions.hidden = !alert;
    nodes.dispatch.disabled = !ready;

    var chosen = state.ranked.concat(state.roster).filter(function (agent) {
      return agent.id === state.selectedAgent;
    })[0];

    nodes.dispatch.textContent = chosen
      ? "Dispatch " + chosen.name
      : "Choose an agent";
  }

  function renderMissions() {
    var missions = openMissions();
    nodes.missions.textContent = "";
    nodes.missionCount.textContent = missions.length;

    if (!missions.length) {
      nodes.missions.appendChild(el("p", "empty", "No mission is running."));
      return;
    }

    missions.forEach(function (mission) {
      var card = el("div", "mission");

      var top = el("div", "mission__top");
      top.appendChild(el("span", "mission__id", "Mission " + mission.id));
      var label = MISSION_LABEL[mission.status];
      top.appendChild(el("span", "badge " + label.cls, label.text));
      card.appendChild(top);

      card.appendChild(
        el("div", "mission__who", mission.agent_name + " → device " + mission.subject_device_id)
      );

      if (mission.status === MISSION.JUST_DEFINED) {
        card.appendChild(
          el(
            "div",
            "mission__when",
            "Waiting for " + mission.agent_name + "'s device to confirm."
          )
        );
      } else if (mission.acknowledged_at) {
        card.appendChild(
          el(
            "div",
            "mission__when",
            "acknowledged " +
              clockOf(mission.acknowledged_at) +
              " · " +
              agoOf(mission.acknowledged_at)
          )
        );
      }

      var actions = el("div", "mission__actions");

      if (mission.status === MISSION.REPORTED) {
        card.appendChild(
          el(
            "div",
            "mission__when",
            "Reported " +
              (OUTCOME_LABEL[mission.outcome] || "").toLowerCase() +
              " at " +
              clockOf(mission.reported_at) +
              ". " +
              mission.agent_name +
              " stays committed until you close it."
          )
        );

        var group = el("div", "mission__actions");
        [OUTCOME.SUCCESS, OUTCOME.FAILURE].forEach(function (value) {
          var id = "outcome-" + mission.id + "-" + value;
          var label = document.createElement("label");
          label.setAttribute("for", id);
          label.style.display = "flex";
          label.style.alignItems = "center";
          label.style.gap = "6px";
          label.style.fontSize = "13px";

          var radio = document.createElement("input");
          radio.type = "radio";
          radio.name = "outcome-" + mission.id;
          radio.id = id;
          radio.value = value;
          radio.checked = mission.outcome === value;

          label.appendChild(radio);
          label.appendChild(
            document.createTextNode(
              OUTCOME_LABEL[value] +
                (mission.outcome === value ? " (as reported)" : "")
            )
          );
          group.appendChild(label);
        });
        card.appendChild(group);

        var finalise = el("button", "btn btn--go btn--small", "Finalise mission");
        finalise.type = "button";
        finalise.addEventListener("click", function () {
          var picked = card.querySelector(
            'input[name="outcome-' + mission.id + '"]:checked'
          );
          send({
            type: "finalize",
            mission_id: mission.id,
            outcome: picked ? Number(picked.value) : mission.outcome,
          });
        });
        actions.appendChild(finalise);
      } else {
        var abort = el("button", "btn btn--danger btn--small", "Call off mission");
        abort.type = "button";
        abort.addEventListener("click", function () {
          send({ type: "abort", mission_id: mission.id });
        });
        actions.appendChild(abort);
      }

      card.appendChild(actions);
      nodes.missions.appendChild(card);
    });
  }

  function render() {
    renderError();
    renderAlerts();
    renderAgents();
    renderActions();
    renderMissions();
  }

  // -------------------------------------------------------------- actions --

  function selectAlert(id) {
    state.selectedAlert = id;
    state.selectedAgent = null;
    state.ranked = [];
    state.rankedFor = null;

    var alert = state.alerts[id];
    if (alert && window.RESC) {
      window.RESC.focusOn(alert.lat, alert.lng);
    }

    // Ranking only means anything against a place, so it is asked for per
    // alert rather than pushed.
    send({ type: "rank_agents", alert_id: id });
    render();
  }

  var panel = null;

  function send(payload) {
    state.error = null;
    if (panel) {
      panel.send(payload);
    }
  }

  // --------------------------------------------------------------- socket --

  var statusEl = document.getElementById("panel-status");

  function setStatus(status) {
    if (!statusEl) {
      return;
    }
    statusEl.className =
      "status status--" + (status === "live" ? "live" : "down");
    statusEl.querySelector(".status__text").textContent =
      status === "live" ? "Connected" : "Reconnecting…";
  }

  function handle(message) {
    if (message.open_alerts) {
      message.open_alerts.forEach(function (alert) {
        state.alerts[alert.id] = alert;
      });
    }

    if (message.open_missions) {
      message.open_missions.forEach(function (mission) {
        state.missions[mission.id] = mission;
      });
    }

    if (message.alert) {
      var incoming = message.alert;
      var known = state.alerts[incoming.id];
      // A refresh carries no heart rate unless the reading did; keep the last
      // one we saw rather than blanking the chip.
      if (known && (incoming.heartrate === null || incoming.heartrate === undefined)) {
        incoming.heartrate = known.heartrate;
      }
      state.alerts[incoming.id] = incoming;

      if (incoming.status === ALERT.CONVERTED || incoming.status === ALERT.DISMISSED) {
        if (state.selectedAlert === incoming.id) {
          state.selectedAlert = null;
          state.selectedAgent = null;
          state.ranked = [];
          state.rankedFor = null;
        }
      }
    }

    if (message.unoccupied_agents) {
      state.roster = message.unoccupied_agents;
    }

    if (message.ranked_agents) {
      state.ranked = message.ranked_agents;
      state.rankedFor = message.alert_id;
    }

    if (message.mission) {
      state.missions[message.mission.id] = message.mission;

      // A rescued subject stops transmitting, because the device reads their
      // vital signs and it has come off them. Take the marker away now rather
      // than leaving it to age out - and if they are somehow still sending,
      // the next reading puts it straight back, which is the right answer.
      if (message.mission.status === MISSION.CLOSED && window.RESC) {
        window.RESC.dropDevice(0, message.mission.subject_device_id);
      }
    }

    if (message.error) {
      state.error = message.error.message || message.error.code;
    }

    render();
  }

  panel = window.RESC.connect(centerPanelWS, {
    onstatus: setStatus,
    onmessage: handle,
    onrefused: function () {
      state.error = "This account may not use the dispatch panel.";
      render();
    },
  });

  nodes.dispatch.addEventListener("click", function () {
    if (state.selectedAlert === null || state.selectedAgent === null) {
      return;
    }
    send({
      type: "dispatch",
      alert_id: state.selectedAlert,
      agent_id: state.selectedAgent,
    });
  });

  nodes.dismiss.addEventListener("click", function () {
    if (state.selectedAlert === null) {
      return;
    }
    send({ type: "dismiss", alert_id: state.selectedAlert });
  });

  render();

  // Keeps the "x min ago" lines honest without the server having to re-send.
  window.setInterval(render, 30000);
})();
