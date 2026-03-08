/* FlightView — Multi-Theme Display Controller */
(function () {
    "use strict";

    // ── Config ────────────────────────────────────
    var FLIP_STAGGER = 25, FLIP_DURATION = 140;
    var RADAR_MAX_FT = 5000;

    // ── State ─────────────────────────────────────
    var theme = localStorage.getItem("fv_theme") || "classic";
    var currentView = "multi";
    var currentFlightId = null;
    var prevScreen = null;
    var latestState = null;

    // ── DOM refs ──────────────────────────────────
    var screens = {
        "classic-multi":  document.getElementById("screen-classic-multi"),
        "classic-single": document.getElementById("screen-classic-single"),
        "modern-multi":   document.getElementById("screen-modern-multi"),
        "modern-single":  document.getElementById("screen-modern-single"),
        "config":         document.getElementById("screen-config"),
    };
    var btnTheme = document.getElementById("btn-theme");
    var btnConfig = document.getElementById("btn-config");
    var btnCfgClose = document.getElementById("btn-cfg-close");
    var btnCfgSave = document.getElementById("btn-cfg-save");
    var btnCfgCancel = document.getElementById("btn-cfg-cancel");

    // Classic single refs
    var CL = {
        card: document.querySelector(".cl-card"),
        flight: document.getElementById("cl-s-flight"),
        count: document.getElementById("cl-s-count"),
        conn: document.getElementById("cl-s-conn"),
        airline: document.getElementById("cl-airline-flaps"),
        type: document.getElementById("cl-type"),
        reg: document.getElementById("cl-reg"),
        routeRow: document.getElementById("cl-route-row"),
        origin: document.getElementById("cl-origin"),
        dest: document.getElementById("cl-dest"),
        alt: document.getElementById("cl-alt"),
        spd: document.getElementById("cl-spd"),
        dist: document.getElementById("cl-dist"),
        vs: document.getElementById("cl-vs"),
        dir: document.getElementById("cl-dir"),
        compass: document.getElementById("cl-compass"),
        hdg: document.getElementById("cl-hdg"),
    };

    // Classic multi refs
    var CLM = {
        count: document.getElementById("cl-m-count"),
        conn: document.getElementById("cl-m-conn"),
        board: document.getElementById("cl-board"),
        empty: document.getElementById("cl-board-empty"),
    };

    // Modern single refs
    var MD = {
        card: document.querySelector(".md-card"),
        badge: document.getElementById("md-s-badge"),
        count: document.getElementById("md-s-count"),
        conn: document.getElementById("md-s-conn"),
        airline: document.getElementById("md-airline"),
        type: document.getElementById("md-type"),
        reg: document.getElementById("md-reg"),
        routeRow: document.getElementById("md-route-row"),
        origin: document.getElementById("md-origin"),
        dest: document.getElementById("md-dest"),
        alt: document.getElementById("md-alt"),
        spd: document.getElementById("md-spd"),
        dist: document.getElementById("md-dist"),
        vrate: document.getElementById("md-vrate"),
        dir: document.getElementById("md-dir"),
        compass: document.getElementById("md-compass"),
        hdg: document.getElementById("md-hdg"),
    };

    // Modern multi refs
    var MDM = {
        count: document.getElementById("md-m-count"),
        conn: document.getElementById("md-m-conn"),
        radar: document.getElementById("md-radar"),
        list: document.getElementById("md-list"),
    };

    // Config refs
    var CFG = {
        lat: document.getElementById("cfg-lat"),
        lon: document.getElementById("cfg-lon"),
        alt: document.getElementById("cfg-alt"),
        radius: document.getElementById("cfg-radius"),
        radarAlt: document.getElementById("cfg-radar-alt"),
        radarRadius: document.getElementById("cfg-radar-radius"),
        poll: document.getElementById("cfg-poll"),
        mock: document.getElementById("cfg-mock"),
        apikey: document.getElementById("cfg-apikey"),
    };

    // ── Screen Manager ────────────────────────────
    function showScreen(id) {
        if (prevScreen === id) return;
        for (var k in screens) {
            screens[k].classList.toggle("active", k === id);
        }
        prevScreen = id;
    }

    function resolveScreen() {
        if (prevScreen === "config") return;
        var s = latestState;
        var hasDisplay = s && s.display;
        currentView = hasDisplay ? "single" : "multi";
        showScreen(theme + "-" + currentView);
    }

    function switchTheme() {
        theme = theme === "classic" ? "modern" : "classic";
        localStorage.setItem("fv_theme", theme);
        btnTheme.textContent = theme.toUpperCase();
        showScreen(theme + "-" + currentView);
        if (latestState) updateAll(latestState);
    }

    // ── Flap Engine ───────────────────────────────
    function createCell() {
        var c = document.createElement("span"); c.className = "flap";
        var ch = document.createElement("span"); ch.className = "flap__char";
        c.appendChild(ch); return c;
    }

    function updateFlaps(container, text, sz) {
        var chars = text.split("");
        container.className = "flaps " + sz;
        while (container.children.length > chars.length) container.removeChild(container.lastChild);
        while (container.children.length < chars.length) container.appendChild(createCell());
        var delay = 0;
        for (var i = 0; i < chars.length; i++) {
            var cell = container.children[i];
            var el = cell.querySelector(".flap__char");
            var isSpace = chars[i] === " ";
            cell.classList.toggle("flap--space", isSpace);
            if (el.textContent !== chars[i]) { schedFlip(cell, el, chars[i], delay); delay += FLIP_STAGGER; }
        }
    }

    function schedFlip(cell, el, ch, d) {
        setTimeout(function () {
            el.textContent = ch;
            cell.classList.remove("flipping"); void cell.offsetWidth;
            cell.classList.add("flipping");
            setTimeout(function () { cell.classList.remove("flipping"); }, FLIP_DURATION);
        }, d);
    }

    // ── Helpers ────────────────────────────────────
    function fmt(v) { return (v == null || isNaN(v)) ? "—" : String(Math.round(v)); }
    function fmtU(v, u) { return (v == null || isNaN(v)) ? "—" : Math.round(v).toLocaleString("en-US") + " " + u; }
    function fmtSigned(v) { if (v == null || isNaN(v)) return " ---"; var n = Math.round(v); return (n >= 0 ? "+" : "") + n; }
    function pad(s, n) { while (s.length < n) s = " " + s; return s; }
    function dirCls(d) { d = (d || "").toLowerCase(); return (d === "approaching" || d === "departing" || d === "overhead") ? d : ""; }

    function setConn(els, connected) {
        for (var i = 0; i < els.length; i++) {
            els[i].className = "hdr-conn " + (connected ? "ok" : "err");
        }
    }

    // ── Classic Single Renderer ───────────────────
    function updateClassicSingle(a, count) {
        CL.flight.textContent = a.flight_display || a.callsign_raw || "—";
        CL.count.textContent = count + " NEARBY";
        updateFlaps(CL.airline, (a.airline || "UNKNOWN").toUpperCase(), "flaps--xl");
        CL.type.textContent = a.aircraft_type || "Unknown Aircraft";
        CL.reg.textContent = a.registration || "";

        if (a.route_origin && a.route_destination) {
            CL.routeRow.classList.remove("no-route");
            updateFlaps(CL.origin, a.route_origin.toUpperCase(), "flaps--lg");
            updateFlaps(CL.dest, a.route_destination.toUpperCase(), "flaps--lg");
        } else {
            CL.routeRow.classList.add("no-route");
        }

        updateFlaps(CL.alt, pad(fmt(a.altitude_ft), 4), "flaps--sm");
        updateFlaps(CL.spd, pad(fmt(a.velocity_kts), 3), "flaps--sm");
        updateFlaps(CL.dist, pad(fmt(a.distance_ft), 4), "flaps--sm");
        updateFlaps(CL.vs, pad(fmtSigned(a.vertical_rate_fpm), 5), "flaps--sm");

        var d = (a.direction || "").toLowerCase();
        CL.dir.textContent = d ? d.toUpperCase() : "—";
        CL.dir.className = "cl-dir " + dirCls(d);
        CL.compass.textContent = a.compass ? "from " + a.compass : "";
        CL.hdg.textContent = a.heading != null ? fmt(a.heading) + "°" : "";
    }

    // ── Classic Multi Renderer ────────────────────
    function updateClassicMulti(list, count) {
        CLM.count.textContent = count + " AIRCRAFT";

        if (list.length === 0) {
            CLM.empty.classList.remove("hidden");
            CLM.board.innerHTML = "";
            return;
        }
        CLM.empty.classList.add("hidden");

        var frag = document.createDocumentFragment();
        for (var i = 0; i < list.length && i < 8; i++) {
            frag.appendChild(buildCardStrip(list[i]));
        }
        CLM.board.innerHTML = "";
        CLM.board.appendChild(frag);
    }

    function buildCardStrip(ac) {
        var d = (ac.direction || "").toLowerCase();
        var card = document.createElement("div");
        card.className = "cl-strip " + dirCls(d);

        // Left: flight + airline
        var left = document.createElement("div"); left.className = "cl-strip__left";
        var fl = document.createElement("span"); fl.className = "cl-strip__flight";
        fl.textContent = ac.flight_display || ac.callsign || "???";
        var al = document.createElement("span"); al.className = "cl-strip__airline";
        al.textContent = ac.airline || "Unknown";
        left.appendChild(fl); left.appendChild(al);

        // Center: route (if available)
        var route = document.createElement("div"); route.className = "cl-strip__route";
        if (ac.route_origin && ac.route_destination) {
            var orig = document.createElement("span"); orig.className = "cl-strip__iata";
            orig.textContent = ac.route_origin;
            var arrow = document.createElement("span"); arrow.className = "cl-strip__arrow";
            arrow.textContent = "✈";
            var dest = document.createElement("span"); dest.className = "cl-strip__iata";
            dest.textContent = ac.route_destination;
            route.appendChild(orig); route.appendChild(arrow); route.appendChild(dest);
        }

        // Stats
        var stats = document.createElement("div"); stats.className = "cl-strip__stats";
        stats.appendChild(buildStripStat(fmt(ac.altitude_ft), "ALT"));
        stats.appendChild(buildStripStat(fmt(ac.distance_ft), "DIST"));

        card.appendChild(left); card.appendChild(route);
        card.appendChild(stats);
        return card;
    }

    function buildStripStat(val, lbl) {
        var d = document.createElement("div"); d.className = "cl-strip-stat";
        var v = document.createElement("span"); v.className = "cl-strip-stat__val"; v.textContent = val;
        var l = document.createElement("span"); l.className = "cl-strip-stat__lbl"; l.textContent = lbl;
        d.appendChild(v); d.appendChild(l); return d;
    }

    function fillFlapsStatic(container, text, sz) {
        container.className = "flaps " + sz;
        var chars = text.toUpperCase().split("");
        for (var i = 0; i < chars.length; i++) {
            var c = createCell();
            c.querySelector(".flap__char").textContent = chars[i];
            if (chars[i] === " ") c.classList.add("flap--space");
            container.appendChild(c);
        }
    }

    function padRight(s, n) { while (s.length < n) s = s + " "; return s.substring(0, n); }

    // ── Modern Single Renderer ────────────────────
    function updateModernSingle(a, count) {
        MD.badge.textContent = a.flight_display || a.callsign_raw || "—";
        MD.count.textContent = count + " nearby";
        MD.airline.textContent = a.airline || "Unknown";
        MD.type.textContent = a.aircraft_type || "Unknown Aircraft";
        MD.reg.textContent = a.registration || "";

        if (a.route_origin && a.route_destination) {
            MD.routeRow.classList.remove("no-route");
            MD.origin.textContent = a.route_origin;
            MD.dest.textContent = a.route_destination;
        } else {
            MD.routeRow.classList.add("no-route");
        }

        MD.alt.textContent = fmtU(a.altitude_ft, "ft");
        MD.spd.textContent = fmtU(a.velocity_kts, "kts");
        MD.dist.textContent = fmtU(a.distance_ft, "ft");
        MD.vrate.textContent = fmtSigned(a.vertical_rate_fpm) + " fpm";

        var d = (a.direction || "").toLowerCase();
        MD.dir.textContent = d ? d.charAt(0).toUpperCase() + d.slice(1) : "—";
        MD.dir.className = "md-dir " + dirCls(d);
        MD.compass.textContent = a.compass ? "from " + a.compass : "";
        MD.hdg.textContent = a.heading != null ? fmt(a.heading) + "°" : "";
    }

    // ── Modern Multi (Radar) Renderer ─────────────
    var radarBlips = {};

    function updateModernMulti(list, count) {
        MDM.count.textContent = count + " aircraft";
        updateRadarBlips(list);
        updateRadarList(list);
    }

    function updateRadarBlips(list) {
        var radar = MDM.radar;
        var rect = radar.getBoundingClientRect();
        var scopeW = rect.width, scopeH = rect.height;
        var cx = scopeW / 2, cy = scopeH / 2;
        var scopeR = (Math.min(scopeW, scopeH) / 2) - 20;
        var seen = {};

        for (var i = 0; i < list.length; i++) {
            var ac = list[i];
            var id = ac.icao24;
            seen[id] = true;

            var bearing = (ac.bearing || 0) * Math.PI / 180;
            var dist = ac.distance_ft || 0;
            var r = Math.min(dist / RADAR_MAX_FT, 1) * scopeR;
            var x = cx + r * Math.sin(bearing);
            var y = cy - r * Math.cos(bearing);

            var blip = radarBlips[id];
            if (!blip) {
                blip = document.createElement("div"); blip.className = "md-blip";
                var dot = document.createElement("div"); dot.className = "md-blip__dot";
                var lbl = document.createElement("span"); lbl.className = "md-blip__label";
                blip.appendChild(dot); blip.appendChild(lbl);
                radar.appendChild(blip);
                radarBlips[id] = blip;
            }
            blip.style.left = x + "px";
            blip.style.top = y + "px";
            blip.querySelector(".md-blip__label").textContent = ac.flight_display || ac.callsign || ac.icao24;
        }

        // Remove stale blips
        for (var bid in radarBlips) {
            if (!seen[bid]) {
                radarBlips[bid].parentNode.removeChild(radarBlips[bid]);
                delete radarBlips[bid];
            }
        }
    }

    function updateRadarList(list) {
        var container = MDM.list;
        if (list.length === 0) {
            container.innerHTML = '<div class="md-list__empty">No aircraft detected</div>';
            return;
        }
        var frag = document.createDocumentFragment();
        for (var i = 0; i < list.length && i < 10; i++) {
            var ac = list[i];
            var item = document.createElement("div"); item.className = "md-list-item";

            var fl = document.createElement("span"); fl.className = "md-li__flight";
            fl.textContent = ac.flight_display || ac.callsign || ac.icao24;

            var orig = document.createElement("span"); orig.className = "md-li__orig";
            orig.textContent = ac.route_origin || "";

            var arrow = document.createElement("span"); arrow.className = "md-li__arrow";
            arrow.textContent = (ac.route_origin && ac.route_destination) ? "→" : "";

            var dest = document.createElement("span"); dest.className = "md-li__dest";
            dest.textContent = ac.route_destination || "";

            var tc = ac.aircraft_type || "";
            var codeParts = tc.split(" ");
            var typeCode = codeParts.length > 1 ? codeParts[codeParts.length - 1] : tc;
            var tp = document.createElement("span"); tp.className = "md-li__type";
            tp.textContent = typeCode;

            var stats = document.createElement("div"); stats.className = "md-li__stats";
            stats.innerHTML = '<span class="md-li__stat">' + fmt(ac.altitude_ft) + ' <span class="md-li__unit">ft</span></span>'
                + '<span class="md-li__stat">' + fmt(ac.distance_ft) + ' <span class="md-li__unit">ft</span></span>';

            item.appendChild(fl); item.appendChild(orig); item.appendChild(arrow);
            item.appendChild(dest); item.appendChild(tp);
            item.appendChild(stats);
            frag.appendChild(item);
        }
        container.innerHTML = "";
        container.appendChild(frag);
    }

    // ── Update Router ─────────────────────────────
    function updateAll(state) {
        var nearCount = state.nearby_count || 0;
        var totalCount = state.aircraft_count || 0;
        var list = state.aircraft_list || [];
        var display = state.display;

        // Multi-plane views show total aircraft in radar zone
        updateClassicMulti(list, totalCount);
        updateModernMulti(list, totalCount);
        // Single-plane views show near zone count
        if (display) updateClassicSingle(display, nearCount);
        if (display) updateModernSingle(display, nearCount);
    }

    // ── Config Screen ─────────────────────────────
    function openConfig() {
        fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
            CFG.lat.value = cfg.home_lat;
            CFG.lon.value = cfg.home_lon;
            CFG.alt.value = cfg.altitude_limit_ft;
            CFG.radius.value = cfg.radius_limit_ft;
            CFG.radarAlt.value = cfg.radar_altitude_ft;
            CFG.radarRadius.value = cfg.radar_radius_ft;
            CFG.poll.value = cfg.poll_interval_sec;
            CFG.apikey.value = cfg.adsbx_api_key || "";
            CFG.mock.textContent = cfg.mock_mode ? "ON" : "OFF";
            CFG.mock.classList.toggle("on", cfg.mock_mode);
            showScreen("config");
        });
    }

    function closeConfig() {
        prevScreen = null;
        resolveScreen();
    }

    function saveConfig() {
        var data = {
            home_lat: parseFloat(CFG.lat.value),
            home_lon: parseFloat(CFG.lon.value),
            altitude_limit_ft: parseInt(CFG.alt.value),
            radius_limit_ft: parseInt(CFG.radius.value),
            radar_altitude_ft: parseInt(CFG.radarAlt.value),
            radar_radius_ft: parseInt(CFG.radarRadius.value),
            poll_interval_sec: parseInt(CFG.poll.value),
            adsbx_api_key: CFG.apikey.value,
            mock_mode: CFG.mock.textContent === "ON",
        };
        fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }).then(function () { closeConfig(); });
    }

    function toggleMock() {
        var isOn = CFG.mock.textContent === "ON";
        CFG.mock.textContent = isOn ? "OFF" : "ON";
        CFG.mock.classList.toggle("on", !isOn);
    }

    // ── Events ────────────────────────────────────
    btnTheme.addEventListener("click", switchTheme);
    btnConfig.addEventListener("click", openConfig);
    btnCfgClose.addEventListener("click", closeConfig);
    btnCfgSave.addEventListener("click", saveConfig);
    btnCfgCancel.addEventListener("click", closeConfig);
    CFG.mock.addEventListener("click", toggleMock);

    // ── Socket.IO ─────────────────────────────────
    var connEls = [
        document.getElementById("cl-m-conn"),
        document.getElementById("cl-s-conn"),
        document.getElementById("md-m-conn"),
        document.getElementById("md-s-conn"),
    ];

    var socket = io({ reconnection: true, reconnectionDelay: 1000 });

    socket.on("connect", function () {
        setConn(connEls, true);
        socket.emit("request_update");
    });
    socket.on("disconnect", function () { setConn(connEls, false); });

    socket.on("aircraft_update", function (state) {
        latestState = state;
        if (state.aircraft_list && state.aircraft_list.length > 0) {
            var first = state.aircraft_list[0];
            console.log("DEBUG route data:", first.callsign, "origin:", first.route_origin, "dest:", first.route_destination);
        }
        resolveScreen();
        updateAll(state);
    });

    // ── Init ──────────────────────────────────────
    btnTheme.textContent = theme.toUpperCase();
    showScreen(theme + "-multi");
    console.log("FlightView multi-theme display loaded");
})();
