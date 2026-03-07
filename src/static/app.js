// FlightView — Frontend application

(function () {
    "use strict";

    // DOM elements
    const flightCard = document.getElementById("flight-card");
    const emptyState = document.getElementById("empty-state");
    const nearbyCount = document.getElementById("nearby-count");
    const airlineName = document.getElementById("airline-name");
    const flightNumber = document.getElementById("flight-number");
    const aircraftType = document.getElementById("aircraft-type");
    const routeOrigin = document.getElementById("route-origin");
    const routeDest = document.getElementById("route-dest");
    const altitude = document.getElementById("altitude");
    const speed = document.getElementById("speed");
    const distance = document.getElementById("distance");
    const direction = document.getElementById("direction");
    const compass = document.getElementById("compass");
    const connDot = document.getElementById("conn-dot");
    const connLabel = document.getElementById("conn-label");

    let currentFlightId = null;

    function formatNumber(val) {
        if (val == null || isNaN(val)) return "—";
        return Math.round(val).toLocaleString("en-US");
    }

    function setConnectionStatus(connected) {
        connDot.className = "conn-dot " + (connected ? "connected" : "disconnected");
        connLabel.textContent = connected ? "Connected" : "Disconnected";
    }

    function directionIcon(dir) {
        if (!dir) return "";
        const d = dir.toLowerCase();
        if (d === "approaching") return "↓ ";
        if (d === "departing") return "↑ ";
        if (d === "overhead") return "● ";
        return "";
    }

    function directionClass(dir) {
        if (!dir) return "";
        const d = dir.toLowerCase();
        if (d === "approaching" || d === "departing" || d === "overhead") return d;
        return "";
    }

    function updateCard(aircraft) {
        if (!aircraft) {
            flightCard.classList.add("hidden");
            emptyState.classList.remove("hidden");
            currentFlightId = null;
            return;
        }

        const newId = aircraft.flight_display || aircraft.icao || "";
        const changed = newId !== currentFlightId;

        if (changed) {
            // Fade out, update, fade in
            flightCard.classList.add("fade-out");
            setTimeout(function () {
                applyData(aircraft);
                flightCard.classList.remove("fade-out");
            }, 150);
        } else {
            applyData(aircraft);
        }

        currentFlightId = newId;
        emptyState.classList.add("hidden");
        flightCard.classList.remove("hidden");
    }

    function applyData(a) {
        airlineName.textContent = a.airline || "Unknown Airline";
        flightNumber.textContent = a.flight_display || "—";
        aircraftType.textContent = a.aircraft_type || "Unknown Aircraft";

        // Route
        if (a.route_display) {
            const parts = a.route_display.split("→").map(function (s) { return s.trim(); });
            routeOrigin.textContent = parts[0] || "—";
            routeDest.textContent = parts[1] || "—";
        } else {
            routeOrigin.textContent = "—";
            routeDest.textContent = "—";
        }

        // Stats
        altitude.textContent = a.altitude_ft != null ? formatNumber(a.altitude_ft) + " ft" : "—";
        speed.textContent = a.velocity_kts != null ? formatNumber(a.velocity_kts) + " kts" : "—";
        distance.textContent = a.distance_ft != null ? formatNumber(a.distance_ft) + " ft" : "—";

        // Direction badge
        const dir = a.direction || "";
        direction.textContent = directionIcon(dir) + dir;
        direction.className = "direction-badge " + directionClass(dir);

        // Compass
        compass.textContent = a.compass ? "from " + a.compass : "";
    }

    // Socket.IO connection
    const socket = io({ reconnection: true, reconnectionDelay: 1000 });

    socket.on("connect", function () {
        setConnectionStatus(true);
        socket.emit("request_update");
    });

    socket.on("disconnect", function () {
        setConnectionStatus(false);
    });

    socket.on("aircraft_update", function (state) {
        // Update nearby count
        var count = (state && state.nearby_count) || 0;
        nearbyCount.textContent = count + " nearby";

        // Update flight card
        updateCard(state ? state.display : null);
    });

    console.log("FlightView frontend loaded");
})();
