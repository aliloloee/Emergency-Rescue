document.addEventListener("DOMContentLoaded", function () {
  // Fetch the Django config first
  fetch("config/") // Adjust URL as necessary
    .then((response) => response.json())
    .then((data) => {
      const DJANGO_SETTINGS_MODULE = data.DJANGO_SETTINGS_MODULE;

      // Define baseURL and wsBaseURL based on DJANGO_SETTINGS_MODULE
      let baseURL;
      const httpProtocol =
        window.location.protocol === "https:" ? "https" : "http";
      const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
      const host = window.location.host;

      if (DJANGO_SETTINGS_MODULE === "resc.settings.developement") {
        console.log("Development environment");
      } else if (DJANGO_SETTINGS_MODULE === "resc.settings.production") {
        console.log("Production environment");
        // baseURL = "localhost"; // Is this needed in production mode ?
      }

      baseURL = `${httpProtocol}://${host}`;
      wsBaseURL = `${wsProtocol}://${host}`;
      // console.log("Base URL:", baseURL);
      // console.log("Base WS URL:", wsBaseURL);

      // Now you can create your axios instance using baseURL
      const axiosInstance = axios.create({
        baseURL: baseURL,
        withCredentials: true,
      });

      async function refreshAuthToken() {
        try {
          const response = await axiosInstance.post(
            refreshTokenUrl,
            {},
            { withCredentials: true }
          );
          console.log("Token refreshed successfully");
          return response;
        } catch (error) {
          if (error.response && error.response.status === 401) {
            window.location.href = logoutUrl;
          } else {
            console.error("Error refreshing token:", error);
          }
        }
      }

      // Setup axios interceptors
      axiosInstance.interceptors.request.use(
        async (config) => {
          return config;
        },
        (error) => {
          return Promise.reject(error);
        }
      );

      axiosInstance.interceptors.response.use(
        (response) => {
          return response;
        },
        async (error) => {
          const originalRequest = error.config;

          if (
            error.response &&
            error.response.status === 401 &&
            !originalRequest._retry
          ) {
            originalRequest._retry = true;

            const refreshResponse = await refreshAuthToken();
            if (refreshResponse && refreshResponse.status === 200) {
              return axiosInstance(originalRequest);
            }
          }

          return Promise.reject(error);
        }
      );

      // Initialize the map and WebSocket connections after config is loaded
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
        var locLat = location[0];
        var locLng = location[1];
        var userStr = location[2];
        if (location.length === 4) {
          var otherMarker = L.marker([locLat, locLng], {
            icon: selfCenterIcon,
          }).addTo(map);
          otherMarker.bindPopup(
            "<b>" + userStr + "</b><br>This is another location."
          );
        } else {
          var otherMarker = L.marker([locLat, locLng], {
            icon: otherCenterIcon,
          }).addTo(map);
          otherMarker.bindPopup(
            "<b>" + userStr + "</b><br>This is another location."
          );
        }
      });

      function connectWebSocket() {
        const socketUrl = `${wsBaseURL}/${centerRecieveWS}`;
        console.log("Connecting to WebSocket:", socketUrl);
        let socket = new WebSocket(socketUrl);

        socket.onopen = async function () {
          console.log("WebSocket connection established.");
        };

        socket.onmessage = function (event) {
          const data = JSON.parse(event.data).device_data;

          if (data.type === 0) {
            handleTypeZeroMessage(data);
          } else if (data.type === 1) {
            handleTypeOneMessage(data);
          } else {
            console.warn("Unknown message type:", data.type);
          }
        };

        socket.onclose = function (event) {
          console.log("WebSocket connection closed:", event.code);
          if (event.code === 4001) {
            refreshAuthToken()
              .then(() => {
                connectWebSocket();
              })
              .catch((error) => {
                console.log("Error refreshing token:", error);
                if (error.response && error.response.status === 401) {
                  window.location.href = logoutUrl;
                }
              });
          }
        };

        socket.onerror = function (error) {
          console.error("WebSocket error:", error);
        };

        return socket;
      }

      // Create a global object to store markers by their 'pk'
      let markersMap = {};

      //Define the icons for type 0 and type 1 markers
      const typeZeroIcon = L.icon({
        iconUrl: subjectIconSrc,
        iconSize: [38, 38],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
      });

      const typeOneIcon = L.icon({
        iconUrl: agentIconSrc,
        iconSize: [38, 38],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
      });

      function handleTypeZeroMessage(data) {
        const { heartrate, lat, lng, pk, region, timestamp, type } = data;
        let id = `${type}-${pk}`;
        console.log("id", id);
        console.log("Latitude:", lat, "Longitude:", lng, "PK:", pk);

        // Check if a marker with the same pk already exists
        if (markersMap[id]) {
          // Remove the old marker from the map
          map.removeLayer(markersMap[id]);
        }

        // Create a new marker with the appropriate icon for type 1
        const marker = L.marker([lat, lng], {
          icon: typeZeroIcon, // Use the icon for type 1
        }).addTo(map);

        // Bind a popup to the marker with the relevant information
        marker.bindPopup("<b>Heartrate:</b> " + heartrate).openPopup();

        // Store the new marker in the markersMap by its 'pk'
        markersMap[id] = marker;
      }

      function handleTypeOneMessage(data) {
        const { lat, lng, pk, region, timestamp, type } = data;
        const id = pk + type;

        // Check if a marker with the same pk already exists
        if (markersMap[id]) {
          // Remove the old marker from the map
          map.removeLayer(markersMap[id]);
        }

        // Create a new marker with the appropriate icon for type 0
        const marker = L.marker([lat, lng], {
          icon: typeOneIcon, // Use the icon for type 0
        }).addTo(map);

        // Bind a popup to the marker with the relevant information
        marker.bindPopup("<b>Agent:</b>");

        // Store the new marker in the markersMap by its 'pk'
        markersMap[id] = marker;
      }

      // Add event listener to button to connect WebSocket
      document
        .getElementById("myButton")
        .addEventListener("click", function () {
          console.log("Button clicked! Connecting to WebSocket...");
          connectWebSocket();
        });

      // Optionally, call refreshAuthToken initially if required
      refreshAuthToken();
    })
    .catch((error) => {
      console.error("Error fetching the config:", error);
    });
});
