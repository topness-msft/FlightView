/* FlightView — Multi-Theme Display Controller */
(function () {
    "use strict";

    // ── Config ────────────────────────────────────
    var FLIP_STAGGER = 25, FLIP_DURATION = 140;
    var RADAR_MAX_FT = 5000;
    var NEAR_RADIUS_FT = 3000;

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
        typeFlaps: document.getElementById("cl-type-flaps"),
        routeRow: document.getElementById("cl-route-row"),
        routeDm: document.getElementById("cl-route-dotmatrix"),
        dir: document.getElementById("cl-dir"),
        compass: document.getElementById("cl-compass"),
        hdg: document.getElementById("cl-hdg"),
    };

    // Classic multi refs
    var CLM = {
        count: document.getElementById("cl-m-count"),
        conn: document.getElementById("cl-m-conn"),
        radar: document.getElementById("cl-radar"),
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
        datasource: document.getElementById("cfg-datasource"),
        dump1090Url: document.getElementById("cfg-dump1090-url"),
        apikey: document.getElementById("cfg-apikey"),
    };

    // Health banner refs
    var healthBanner = document.getElementById("health-banner");
    var healthTitle = document.getElementById("health-title");
    var healthDetail = document.getElementById("health-detail");

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
        requestAnimationFrame(sizeNearZone);
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
    function shortAirline(s) { return (s || "").replace(/\s*Airlines?\s*/gi, " ").replace(/\s*Air Lines?\s*/gi, " ").trim(); }
    function pad(s, n) { while (s.length < n) s = " " + s; return s; }
    function dirCls(d) { d = (d || "").toLowerCase(); return (d === "approaching" || d === "departing" || d === "overhead") ? d : ""; }

    function setConn(els, connected) {
        for (var i = 0; i < els.length; i++) {
            els[i].className = "hdr-conn " + (connected ? "ok" : "err");
        }
    }

    // ── LED Dot-Matrix Engine ──────────────────────
    // 5×7 pixel font — each char is [row0..row6], each row is 5 bits (MSB=left)
    var DOT_FONT = {
        "A":[14,17,17,31,17,17,17],"B":[30,17,17,30,17,17,30],"C":[14,17,16,16,16,17,14],
        "D":[28,18,17,17,17,18,28],"E":[31,16,16,30,16,16,31],"F":[31,16,16,30,16,16,16],
        "G":[14,17,16,23,17,17,14],"H":[17,17,17,31,17,17,17],"I":[14,4,4,4,4,4,14],
        "J":[7,2,2,2,2,18,12],"K":[17,18,20,24,20,18,17],"L":[16,16,16,16,16,16,31],
        "M":[17,27,21,21,17,17,17],"N":[17,25,21,19,17,17,17],"O":[14,17,17,17,17,17,14],
        "P":[30,17,17,30,16,16,16],"Q":[14,17,17,17,21,18,13],"R":[30,17,17,30,20,18,17],
        "S":[14,17,16,14,1,17,14],"T":[31,4,4,4,4,4,4],"U":[17,17,17,17,17,17,14],
        "V":[17,17,17,17,10,10,4],"W":[17,17,17,21,21,21,10],"X":[17,17,10,4,10,17,17],
        "Y":[17,17,10,4,4,4,4],"Z":[31,1,2,4,8,16,31],
        "0":[14,17,19,21,25,17,14],"1":[4,12,4,4,4,4,14],"2":[14,17,1,2,4,8,31],
        "3":[31,2,4,2,1,17,14],"4":[2,6,10,18,31,2,2],"5":[31,16,30,1,1,17,14],
        "6":[6,8,16,30,17,17,14],"7":[31,1,2,4,8,8,8],"8":[14,17,17,14,17,17,14],
        "9":[14,17,17,15,1,2,12],
        " ":[0,0,0,0,0,0,0],"-":[0,0,0,14,0,0,0],"/":[1,2,2,4,8,8,16],
        "+":[0,4,4,31,4,4,0],".":[0,0,0,0,0,0,4],
    };

    var _dotMatrixCache = {};

    function renderDotMatrix(container, line1, line2) {
        var key = line1 + "|" + line2;
        if (_dotMatrixCache[container.id] === key) return;
        _dotMatrixCache[container.id] = key;

        container.innerHTML = "";
        var panel = document.createElement("div");
        panel.className = "dm-panel";
        panel.appendChild(buildDotLine(line1));
        panel.appendChild(buildDotLine(line2));
        container.appendChild(panel);
    }

    function buildDotLine(text) {
        var row = document.createElement("div");
        row.className = "dm-line";
        text = text.toUpperCase();
        for (var c = 0; c < text.length; c++) {
            var ch = text[c];
            var glyph = DOT_FONT[ch] || DOT_FONT[" "];
            var charEl = document.createElement("div");
            charEl.className = "dm-char";
            for (var r = 0; r < 7; r++) {
                var bits = glyph[r];
                for (var b = 4; b >= 0; b--) {
                    var dot = document.createElement("span");
                    dot.className = (bits >> b) & 1 ? "dm-dot dm-on" : "dm-dot";
                    charEl.appendChild(dot);
                }
            }
            row.appendChild(charEl);
            // gap between chars
            if (c < text.length - 1) {
                var gap = document.createElement("div");
                gap.className = "dm-gap";
                row.appendChild(gap);
            }
        }
        return row;
    }

    // ── Vintage Gauge Engine ─────────────────────────
    var GAUGE_SWEEP = 270; // degrees of arc
    var GAUGE_START = -135; // degrees from 12 o'clock
    var SVG_NS = "http://www.w3.org/2000/svg";

    var gaugeConfigs = {
        "cl-gauge-alt":  { label:"ALTITUDE", unit:"FEET",  min:0, max:45000, majors:[0,5,10,15,20,25,30,35,40,45], divisor:1000 },
        "cl-gauge-spd":  { label:"AIRSPEED", unit:"KNOTS", min:0, max:400,   majors:[0,50,100,150,200,250,300,350,400], divisor:1 },
        "cl-gauge-dist": { label:"DISTANCE", unit:"FEET",  min:0, max:15000, majors:[0,3,6,9,12,15], divisor:1000 },
        "cl-gauge-vs":   { label:"VERT SPD", unit:"FT/MIN",min:-6000, max:6000, majors:[-6,-3,0,3,6], divisor:1000 },
    };

    function buildGaugeSVG(cfg) {
        var svg = document.createElementNS(SVG_NS, "svg");
        svg.setAttribute("viewBox", "0 0 200 200");
        svg.setAttribute("class", "cl-gauge__svg");

        // Bezel — outer ring with gradient effect
        addCircle(svg, 100, 100, 97, "none", "#1A1D24", 6);
        addCircle(svg, 100, 100, 94, "none", "#2A2D34", 1);

        // Face — dark navy
        addCircle(svg, 100, 100, 88, "#1C2030", "none", 0);

        // Inner shadow ring
        addCircle(svg, 100, 100, 88, "none", "rgba(0,0,0,0.3)", 2);

        // Tick marks
        var minorCount = (cfg.majors.length - 1) * 5;
        for (var i = 0; i <= minorCount; i++) {
            var frac = i / minorCount;
            var ang = (GAUGE_START + frac * GAUGE_SWEEP) * Math.PI / 180;
            var isMajor = (i % 5 === 0);
            var r1 = isMajor ? 72 : 78;
            var r2 = 85;
            var x1 = 100 + r1 * Math.sin(ang), y1 = 100 - r1 * Math.cos(ang);
            var x2 = 100 + r2 * Math.sin(ang), y2 = 100 - r2 * Math.cos(ang);
            var line = document.createElementNS(SVG_NS, "line");
            line.setAttribute("x1", x1); line.setAttribute("y1", y1);
            line.setAttribute("x2", x2); line.setAttribute("y2", y2);
            line.setAttribute("stroke", isMajor ? "#D4C9A8" : "#6B6555");
            line.setAttribute("stroke-width", isMajor ? "2" : "1");
            svg.appendChild(line);
        }

        // Number labels at major ticks
        for (var m = 0; m < cfg.majors.length; m++) {
            var mfrac = m / (cfg.majors.length - 1);
            var mang = (GAUGE_START + mfrac * GAUGE_SWEEP) * Math.PI / 180;
            var lr = 62;
            var tx = 100 + lr * Math.sin(mang);
            var ty = 100 - lr * Math.cos(mang);
            var txt = document.createElementNS(SVG_NS, "text");
            txt.setAttribute("x", tx); txt.setAttribute("y", ty);
            txt.setAttribute("text-anchor", "middle");
            txt.setAttribute("dominant-baseline", "central");
            txt.setAttribute("class", "cl-gauge__num");
            txt.textContent = cfg.majors[m];
            svg.appendChild(txt);
        }

        // Triangle index marker at 12 o'clock
        var tri = document.createElementNS(SVG_NS, "polygon");
        tri.setAttribute("points", "100,14 97,20 103,20");
        tri.setAttribute("fill", "#D4C9A8");
        svg.appendChild(tri);

        // Unit label
        var unitTxt = document.createElementNS(SVG_NS, "text");
        unitTxt.setAttribute("x", 100); unitTxt.setAttribute("y", 128);
        unitTxt.setAttribute("text-anchor", "middle");
        unitTxt.setAttribute("class", "cl-gauge__unit-label");
        unitTxt.textContent = cfg.unit;
        svg.appendChild(unitTxt);

        // Needle (will be rotated via transform)
        var needleG = document.createElementNS(SVG_NS, "g");
        needleG.setAttribute("class", "cl-gauge__needle-g");
        // Needle body
        var needle = document.createElementNS(SVG_NS, "line");
        needle.setAttribute("x1", 100); needle.setAttribute("y1", 105);
        needle.setAttribute("x2", 100); needle.setAttribute("y2", 22);
        needle.setAttribute("stroke", "#D4C9A8");
        needle.setAttribute("stroke-width", "2.5");
        needle.setAttribute("stroke-linecap", "round");
        needleG.appendChild(needle);
        // Center cap
        addCircle(needleG, 100, 100, 6, "#3A3530", "#D4C9A8", 1.5);
        // Small center dot (like the red dot in the reference)
        addCircle(needleG, 100, 100, 2.5, "#C45030", "none", 0);
        svg.appendChild(needleG);

        // Mounting screws (4 corners)
        var screwPositions = [[16,16],[184,16],[16,184],[184,184]];
        for (var s = 0; s < screwPositions.length; s++) {
            addCircle(svg, screwPositions[s][0], screwPositions[s][1], 5, "#1A1D24", "#2A2D34", 1);
            // Phillips cross
            var sx = screwPositions[s][0], sy = screwPositions[s][1];
            addScrewLine(svg, sx-2.5, sy, sx+2.5, sy);
            addScrewLine(svg, sx, sy-2.5, sx, sy+2.5);
        }

        return svg;
    }

    function addCircle(parent, cx, cy, r, fill, stroke, sw) {
        var c = document.createElementNS(SVG_NS, "circle");
        c.setAttribute("cx", cx); c.setAttribute("cy", cy); c.setAttribute("r", r);
        c.setAttribute("fill", fill || "none");
        if (stroke && stroke !== "none") { c.setAttribute("stroke", stroke); c.setAttribute("stroke-width", sw); }
        parent.appendChild(c);
    }

    function addScrewLine(svg, x1, y1, x2, y2) {
        var l = document.createElementNS(SVG_NS, "line");
        l.setAttribute("x1", x1); l.setAttribute("y1", y1);
        l.setAttribute("x2", x2); l.setAttribute("y2", y2);
        l.setAttribute("stroke", "#3A3D44"); l.setAttribute("stroke-width", "0.8");
        svg.appendChild(l);
    }

    // Build gauges on init
    for (var gid in gaugeConfigs) {
        var container = document.getElementById(gid);
        if (!container) continue;
        var gsvg = buildGaugeSVG(gaugeConfigs[gid]);
        // Numeric readout overlay
        var readout = document.createElement("div");
        readout.className = "cl-gauge__readout";
        readout.innerHTML = '<span class="cl-gauge__val">—</span>';
        container.appendChild(gsvg);
        container.appendChild(readout);
    }

    function setGauge(id, value) {
        var el = document.getElementById(id);
        if (!el) return;
        var cfg = gaugeConfigs[id];
        var clamped = Math.max(cfg.min, Math.min(cfg.max, value || 0));
        var frac = (clamped - cfg.min) / (cfg.max - cfg.min);
        var angle = GAUGE_START + frac * GAUGE_SWEEP;
        var needleG = el.querySelector(".cl-gauge__needle-g");
        if (needleG) needleG.setAttribute("transform", "rotate(" + angle + " 100 100)");
        var valEl = el.querySelector(".cl-gauge__val");
        if (valEl) valEl.textContent = Math.round(value || 0).toLocaleString("en-US");
    }

    // ── Classic Single Renderer ───────────────────
    function updateClassicSingle(a, count) {
        CL.flight.textContent = a.flight_display || a.callsign_raw || "—";
        CL.count.textContent = count + " NEARBY";
        updateFlaps(CL.airline, (a.airline || "UNKNOWN").toUpperCase(), "flaps--xl");

        // Split-flap: flight code + type code
        var flightCode = a.flight_display || a.callsign_raw || "";
        var tc = a.aircraft_type || "";
        var codeParts = tc.split(" ");
        var typeCode = codeParts.length > 1 ? codeParts[codeParts.length - 1] : tc;
        updateFlaps(CL.typeFlaps, (flightCode + "  " + typeCode).toUpperCase(), "flaps--xl");

        // Dot-matrix: route
        if (a.route_origin && a.route_destination) {
            CL.routeRow.classList.remove("no-route");
            renderDotMatrix(CL.routeDm, a.route_origin + "  -  " + a.route_destination, "");
        } else {
            CL.routeRow.classList.add("no-route");
        }

        setGauge("cl-gauge-alt", a.altitude_ft);
        setGauge("cl-gauge-spd", a.velocity_kts);
        setGauge("cl-gauge-dist", a.distance_ft);
        setGauge("cl-gauge-vs", a.vertical_rate_fpm);

        var d = (a.direction || "").toLowerCase();
        CL.dir.textContent = d ? d.toUpperCase() : "—";
        CL.dir.className = "cl-dir " + dirCls(d);
        CL.compass.textContent = a.compass ? "from " + a.compass : "";
        CL.hdg.textContent = a.heading != null ? fmt(a.heading) + "°" : "";
    }

    // ── Classic Multi Renderer ────────────────────
    var classicBlips = {};

    function updateClassicMulti(list, count) {
        CLM.count.textContent = count + " AIRCRAFT";
        updateClassicRadarBlips(list);

        if (list.length === 0) {
            CLM.empty.classList.remove("hidden");
            // Animate out remaining strips
            CLM.board.querySelectorAll(".cl-strip:not(.removing)").forEach(function(el) {
                el.classList.add("removing");
                el.addEventListener("animationend", function() { el.remove(); }, { once: true });
            });
            return;
        }
        CLM.empty.classList.add("hidden");

        var maxStrips = 8;
        var showList = list.slice(0, maxStrips);
        var newIds = {};
        for (var i = 0; i < showList.length; i++) newIds[showList[i].icao24] = showList[i];

        // Animate out strips no longer in list
        CLM.board.querySelectorAll(".cl-strip:not(.removing)").forEach(function(el) {
            if (!newIds[el.dataset.icao]) {
                el.classList.add("removing");
                el.addEventListener("animationend", function() { el.remove(); }, { once: true });
            }
        });

        // Update or insert strips
        for (var i = 0; i < showList.length; i++) {
            var ac = showList[i];
            var existing = CLM.board.querySelector('.cl-strip[data-icao="' + ac.icao24 + '"]:not(.removing)');
            if (existing) {
                updateCardStrip(existing, ac);
            } else {
                var strip = buildCardStrip(ac);
                strip.dataset.icao = ac.icao24;
                CLM.board.appendChild(strip);
            }
        }
    }

    function updateClassicRadarBlips(list) {
        var radar = CLM.radar;
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

            var blip = classicBlips[id];
            if (!blip) {
                blip = document.createElement("div"); blip.className = "cl-blip";
                var dot = document.createElement("div"); dot.className = "cl-blip__dot";
                var lbl = document.createElement("span"); lbl.className = "cl-blip__label";
                blip.appendChild(dot); blip.appendChild(lbl);
                radar.appendChild(blip);
                classicBlips[id] = blip;
            }
            blip.style.left = x + "px";
            blip.style.top = y + "px";
            var hdg = ac.heading || 0;
            blip.querySelector(".cl-blip__dot").style.transform = "translate(-50%,-50%) rotate(" + hdg + "deg)";
            blip.querySelector(".cl-blip__label").textContent = ac.flight_display || ac.callsign || ac.icao24;
        }

        for (var bid in classicBlips) {
            if (!seen[bid]) {
                classicBlips[bid].parentNode.removeChild(classicBlips[bid]);
                delete classicBlips[bid];
            }
        }
    }

    function buildCardStrip(ac) {
        var d = (ac.direction || "").toLowerCase();
        var card = document.createElement("div");
        card.className = "cl-strip " + dirCls(d);

        var left = document.createElement("div"); left.className = "cl-strip__left";
        var fl = document.createElement("span"); fl.className = "cl-strip__flight";
        fl.textContent = ac.flight_display || ac.callsign || "???";
        left.appendChild(fl);

        var al = document.createElement("span"); al.className = "cl-strip__airline";
        al.textContent = shortAirline(ac.airline);

        var tc = ac.aircraft_type || "";
        var codeParts = tc.split(" ");
        var typeCode = codeParts.length > 1 ? codeParts[codeParts.length - 1] : tc;
        var tp = document.createElement("span"); tp.className = "cl-strip__type";
        tp.textContent = typeCode;

        var stats = document.createElement("div"); stats.className = "cl-strip__stats";
        stats.innerHTML = '<span class="cl-strip-stat__val"><span class="cl-strip-stat__icon">↕</span>' + fmt(ac.altitude_ft) + ' <span class="cl-strip-stat__unit">FT</span></span>'
            + '<span class="cl-strip-stat__val"><span class="cl-strip-stat__icon">↔</span>' + fmt(ac.distance_ft) + ' <span class="cl-strip-stat__unit">FT</span></span>';

        card.appendChild(left); card.appendChild(al);
        card.appendChild(tp); card.appendChild(stats);
        return card;
    }

    function updateCardStrip(card, ac) {
        var d = (ac.direction || "").toLowerCase();
        card.className = "cl-strip " + dirCls(d);

        var fl = card.querySelector(".cl-strip__flight");
        if (fl) fl.textContent = ac.flight_display || ac.callsign || "???";

        var al = card.querySelector(".cl-strip__airline");
        if (al) al.textContent = shortAirline(ac.airline);

        var tc = ac.aircraft_type || "";
        var codeParts = tc.split(" ");
        var typeCode = codeParts.length > 1 ? codeParts[codeParts.length - 1] : tc;
        var tp = card.querySelector(".cl-strip__type");
        if (tp) tp.textContent = typeCode;

        var stats = card.querySelector(".cl-strip__stats");
        if (stats) stats.innerHTML = '<span class="cl-strip-stat__val"><span class="cl-strip-stat__icon">↕</span>' + fmt(ac.altitude_ft) + ' <span class="cl-strip-stat__unit">FT</span></span>'
            + '<span class="cl-strip-stat__val"><span class="cl-strip-stat__icon">↔</span>' + fmt(ac.distance_ft) + ' <span class="cl-strip-stat__unit">FT</span></span>';
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

    // ── Modern Single Renderer (Heathrow signage) ──
    function updateModernSingle(a, count) {
        MD.badge.textContent = a.flight_display || a.callsign_raw || "—";
        MD.count.textContent = count + " nearby";
        MD.airline.textContent = shortAirline(a.airline) || "Unknown";
        MD.type.textContent = a.aircraft_type || "";
        MD.reg.textContent = a.registration ? "· " + a.registration : "";

        if (a.route_origin && a.route_destination) {
            MD.routeRow.style.display = "";
            MD.origin.textContent = a.route_origin;
            MD.dest.textContent = a.route_destination;
        } else {
            MD.routeRow.style.display = "none";
        }

        MD.alt.textContent = (a.altitude_ft != null && !isNaN(a.altitude_ft)) ? Math.round(a.altitude_ft).toLocaleString("en-US") : "—";
        MD.spd.textContent = (a.velocity_kts != null && !isNaN(a.velocity_kts)) ? Math.round(a.velocity_kts).toLocaleString("en-US") : "—";
        MD.dist.textContent = (a.distance_ft != null && !isNaN(a.distance_ft)) ? Math.round(a.distance_ft).toLocaleString("en-US") : "—";
        MD.vrate.textContent = (a.vertical_rate_fpm != null && !isNaN(a.vertical_rate_fpm)) ? fmtSigned(a.vertical_rate_fpm) : "—";

        var d = (a.direction || "").toLowerCase();
        MD.dir.textContent = d ? d.charAt(0).toUpperCase() + d.slice(1) : "—";
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
            var hdg = ac.heading || 0;
            blip.querySelector(".md-blip__dot").style.transform = "translate(-50%,-50%) rotate(" + hdg + "deg)";
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

        var maxItems = 10;
        var existing = container.querySelectorAll(".md-list-item");
        var showCount = Math.min(list.length, maxItems);

        for (var i = 0; i < showCount; i++) {
            var ac = list[i];
            if (i < existing.length) {
                // Update in-place
                var item = existing[i];
                var fl = item.querySelector(".md-li__flight");
                if (fl) fl.textContent = ac.flight_display || ac.callsign || ac.icao24;
                var al = item.querySelector(".md-li__airline");
                if (al) al.textContent = shortAirline(ac.airline);
                var tc = ac.aircraft_type || "";
                var codeParts = tc.split(" ");
                var typeCode = codeParts.length > 1 ? codeParts[codeParts.length - 1] : tc;
                var tp = item.querySelector(".md-li__type");
                if (tp) tp.textContent = typeCode;
                var stats = item.querySelector(".md-li__stats");
                if (stats) stats.innerHTML = '<span class="md-li__stat"><span class="md-li__icon">↕</span>' + fmt(ac.altitude_ft) + ' <span class="md-li__unit">ft</span></span>'
                    + '<span class="md-li__stat"><span class="md-li__icon">↔</span>' + fmt(ac.distance_ft) + ' <span class="md-li__unit">ft</span></span>';
            } else {
                // Build new item
                var item = document.createElement("div"); item.className = "md-list-item";
                var left = document.createElement("div"); left.className = "md-li__left";
                var fl = document.createElement("span"); fl.className = "md-li__flight";
                fl.textContent = ac.flight_display || ac.callsign || ac.icao24;
                left.appendChild(fl);
                var al = document.createElement("span"); al.className = "md-li__airline";
                al.textContent = shortAirline(ac.airline);
                var tc = ac.aircraft_type || "";
                var codeParts = tc.split(" ");
                var typeCode = codeParts.length > 1 ? codeParts[codeParts.length - 1] : tc;
                var tp = document.createElement("span"); tp.className = "md-li__type";
                tp.textContent = typeCode;
                var stats = document.createElement("div"); stats.className = "md-li__stats";
                stats.innerHTML = '<span class="md-li__stat"><span class="md-li__icon">↕</span>' + fmt(ac.altitude_ft) + ' <span class="md-li__unit">ft</span></span>'
                    + '<span class="md-li__stat"><span class="md-li__icon">↔</span>' + fmt(ac.distance_ft) + ' <span class="md-li__unit">ft</span></span>';
                item.appendChild(left); item.appendChild(al);
                item.appendChild(tp); item.appendChild(stats);
                container.appendChild(item);
            }
        }
        // Remove excess items
        for (var j = existing.length - 1; j >= showCount; j--) {
            existing[j].remove();
        }
        // Remove empty-state if present
        var empty = container.querySelector(".md-list__empty");
        if (empty) empty.remove();
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
            CFG.datasource.value = cfg.data_source || "rtlsdr";
            CFG.dump1090Url.value = cfg.dump1090_url || "http://localhost:8080";
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
            data_source: CFG.datasource.value,
            dump1090_url: CFG.dump1090Url.value,
        };
        fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        }).then(function () { closeConfig(); });
    }

    // ── Health Banner ─────────────────────────────
    function updateHealthBanner(health) {
        if (!health || health.status === "ok") {
            healthBanner.classList.remove("visible");
            return;
        }
        var src = (health.data_source || "rtlsdr").toUpperCase();
        var titles = {
            "RTLSDR": "ADS-B receiver offline",
            "OPENSKY": "OpenSky API unreachable",
            "MOCK": "Mock source error",
        };
        healthTitle.textContent = titles[src] || "Data source error";

        var detail = health.message || "Check connection";
        if (health.last_success) {
            var ago = Math.round((Date.now() / 1000 - health.last_success));
            if (ago > 0) detail += " · last data " + ago + "s ago";
        }
        healthDetail.textContent = detail;
        healthBanner.classList.add("visible");
    }

    // ── Events ────────────────────────────────────
    btnTheme.addEventListener("click", switchTheme);
    btnConfig.addEventListener("click", openConfig);
    btnCfgClose.addEventListener("click", closeConfig);
    btnCfgSave.addEventListener("click", saveConfig);
    btnCfgCancel.addEventListener("click", closeConfig);

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
        updateHealthBanner(state.health);
        resolveScreen();
        updateAll(state);
    });

    // ── Init ──────────────────────────────────────
    btnTheme.textContent = theme.toUpperCase();
    showScreen(theme + "-multi");

    // Load config and size near-zone indicators
    fetch("/api/config").then(function(r) { return r.json(); }).then(function(cfg) {
        NEAR_RADIUS_FT = cfg.radius_limit_ft || 3000;
        // Scale scope to show all aircraft — use radar_radius or keep default
        RADAR_MAX_FT = cfg.radar_radius_ft || 60000;
        sizeNearZone();
    });

    function sizeNearZone() {
        var ratio = Math.min(NEAR_RADIUS_FT / RADAR_MAX_FT, 1);
        var zones = [
            { radar: document.getElementById("cl-radar"), zone: document.getElementById("cl-near-zone") },
            { radar: document.getElementById("md-radar"), zone: document.getElementById("md-near-zone") },
        ];
        for (var i = 0; i < zones.length; i++) {
            var z = zones[i];
            if (!z.radar || !z.zone) continue;
            var rect = z.radar.getBoundingClientRect();
            var scopeR = (Math.min(rect.width, rect.height) / 2) - 20;
            var dia = Math.max(Math.round(scopeR * ratio * 2), 30);
            z.zone.style.width = dia + "px";
            z.zone.style.height = dia + "px";
        }
    }
    window.addEventListener("resize", sizeNearZone);

    console.log("FlightView multi-theme display loaded");
})();
