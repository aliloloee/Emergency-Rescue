/*
 * Map and live device markers for the emergency centre dashboard.
 *
 * Also exposes window.RESC: a websocket helper the dispatch panel reuses, so
 * the refresh-and-reconnect behaviour exists once rather than per socket.
 *
 * Close codes come from the consumers (see agents/mixinx.py):
 *   4001  the token is no good - refresh it and try again
 *   4005  this account is not allowed here - retrying would loop for ever
 */
(function () {
  "use strict";

  var wsBase =
    (window.location.protocol === "https:" ? "wss" : "ws") +
    "://" +
    window.location.host;

  function refreshToken() {
    return fetch(refreshTokenUrl, {
      method: "POST",
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.ok;
      })
      .catch(function () {
        return false;
      });
  }

  /*
   * Opens `path` and keeps it open. Returns a handle whose send() always talks
   * to the current socket, so callers need not care that a reconnect replaced
   * it underneath them.
   */
  function connect(path, handlers) {
    var handle = {
      socket: null,
      send: function (payload) {
        if (handle.socket && handle.socket.readyState === WebSocket.OPEN) {
          handle.socket.send(JSON.stringify(payload));
        }
      },
    };

    function report(state) {
      if (handlers.onstatus) {
        handlers.onstatus(state);
      }
    }

    function open() {
      var socket = new WebSocket(wsBase + "/" + path);
      handle.socket = socket;

      socket.onopen = function () {
        report("live");
      };

      socket.onmessage = function (event) {
        handlers.onmessage(JSON.parse(event.data));
      };

      socket.onclose = function (event) {
        report("down");

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
          // Not a transient failure: a new token cannot make this account
          // allowed, so reconnecting would spin.
          if (handlers.onrefused) {
            handlers.onrefused();
          }
          return;
        }

        window.setTimeout(open, 3000);
      };
    }

    open();
    return handle;
  }

  // ------------------------------------------------------------------ map --

  var map = L.map("map").setView([centerLat, centerLng], 14);

  // Attribution is required by the OSM tile usage policy. The {s} subdomain
  // trick is deprecated, and the tiles only load at all if the browser sends
  // a Referer - see SECURE_REFERRER_POLICY in the Django settings.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  var selfCenterIcon = L.AwesomeMarkers.icon({
    icon: "star",
    markerColor: "red",
    prefix: "fa",
  });

  var otherCenterIcon = L.AwesomeMarkers.icon({
    icon: "star",
    markerColor: "blue",
    prefix: "fa",
  });

  locations.forEach(function (location) {
    // A fourth entry marks the centre the operator is signed in as.
    var isSelf = location.length === 4;
    L.marker([location[0], location[1]], {
      icon: isSelf ? selfCenterIcon : otherCenterIcon,
    })
      .addTo(map)
      .bindPopup(
        "<b>" + location[2] + "</b><br>" + (isSelf ? "This centre" : "Emergency centre")
      );
  });

  var deviceIcons = {
    0: L.icon({
      iconUrl: subjectIconSrc,
      iconSize: [38, 38],
      iconAnchor: [19, 38],
      popupAnchor: [0, -34],
    }),
    1: L.icon({
      iconUrl: agentIconSrc,
      iconSize: [38, 38],
      iconAnchor: [19, 38],
      popupAnchor: [0, -34],
    }),
  };

  /*
   * One marker per device, moved rather than rebuilt. Recreating it on every
   * reading made the map flicker and slammed any open popup shut.
   */
  var markers = {};

  function showDevice(data) {
    var id = data.type + "-" + data.pk;
    var marker = markers[id];

    if (marker) {
      marker.setLatLng([data.lat, data.lng]);
    } else {
      marker = L.marker([data.lat, data.lng], { icon: deviceIcons[data.type] });
      marker.addTo(map);
      markers[id] = marker;
    }

    marker.bindPopup(
      data.type === 0
        ? "<b>Subject device " + data.pk + "</b><br>" + data.heartrate + " bpm"
        : "<b>Agent device " + data.pk + "</b>"
    );
  }

  window.RESC = {
    connect: connect,
    wsBase: wsBase,
    focusOn: function (lat, lng) {
      map.setView([lat, lng], Math.max(map.getZoom(), 16));
    },
  };

  // --------------------------------------------------------------- status --

  var statusEl = document.getElementById("map-status");

  function setStatus(state) {
    if (!statusEl) {
      return;
    }
    statusEl.className = "status status--" + (state === "live" ? "live" : "down");
    statusEl.querySelector(".status__text").textContent =
      state === "live" ? "Live" : "Reconnecting…";
  }

  connect(centerRecieveWS, {
    onstatus: setStatus,
    onmessage: function (message) {
      if (message.device_data) {
        showDevice(message.device_data);
      }
    },
  });
})();
