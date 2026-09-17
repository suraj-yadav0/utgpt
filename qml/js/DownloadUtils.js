.pragma library

// Shared pure logic for DownloadPage.qml.
// UI-free so it can run under qmltestrunner (QtTest).

function normalizeFilter(text) {
    if (!text) {
        return "";
    }
    return text.toLowerCase().trim();
}

function catalogItemMatches(item, filterText) {
    if (!filterText) {
        return true;
    }
    var nameMatch = item.name && item.name.toLowerCase().indexOf(filterText) >= 0;
    var descMatch = item.description && item.description.toLowerCase().indexOf(filterText) >= 0;
    var devMatch = item.developer && item.developer.toLowerCase().indexOf(filterText) >= 0;
    var usageMatch = item.usage && item.usage.toLowerCase().indexOf(filterText) >= 0;
    return !!(nameMatch || descMatch || devMatch || usageMatch);
}

function filterCatalog(catalog, rawFilter) {
    var filterText = normalizeFilter(rawFilter);
    var out = [];
    for (var i = 0; i < (catalog || []).length; i++) {
        if (catalogItemMatches(catalog[i], filterText)) {
            out.push(catalog[i]);
        }
    }
    return out;
}

function defaultModelEntry(item) {
    return {
        name: item.name,
        filename: item.filename,
        size: item.size,
        description: item.description,
        url: item.url,
        progress: 0.0,
        downloading: false,
        paused: false,
        ready: false,
        requestId: "",
        compatibility: item.compatibility || "yellow",
        compatibilityText: item.compatibilityText || "Runs Fine"
    };
}

function buildModelEntries(catalog, rawFilter) {
    var items = filterCatalog(catalog, rawFilter);
    var out = [];
    for (var i = 0; i < items.length; i++) {
        out.push(defaultModelEntry(items[i]));
    }
    return out;
}

// Pure version of DownloadPage.updateDownloadStates().
// items: array of model entries, states: {filename: {status, requestId}}.
// Returns a new array, input is left untouched.
function applyDownloadStates(items, states) {
    var out = [];
    for (var row = 0; row < items.length; row++) {
        var src = items[row];
        var next = {
            name: src.name,
            filename: src.filename,
            size: src.size,
            description: src.description,
            url: src.url,
            progress: src.progress,
            downloading: src.downloading,
            paused: src.paused,
            ready: src.ready,
            requestId: src.requestId,
            compatibility: src.compatibility,
            compatibilityText: src.compatibilityText
        };
        var state = states ? states[src.filename] : null;
        if (state) {
            if (state.status === "ready") {
                next.ready = true;
                next.downloading = false;
                next.paused = false;
                next.progress = 1.0;
            } else if (state.status === "downloading") {
                next.ready = false;
                next.downloading = true;
                next.paused = false;
                if (state.requestId) {
                    next.requestId = state.requestId;
                }
            } else if (state.status === "paused") {
                next.ready = false;
                next.downloading = false;
                next.paused = true;
                if (state.requestId) {
                    next.requestId = state.requestId;
                }
            }
        } else {
            next.ready = false;
            next.downloading = false;
            next.paused = false;
            next.progress = 0.0;
        }
        out.push(next);
    }
    return out;
}

function downloadStatusLabel(progress, downloading, paused) {
    if (paused) {
        return "Paused: " + Math.round(progress * 100) + "%";
    }
    if (!downloading) {
        return "";
    }
    if (progress === 0.0) {
        return "Connecting...";
    }
    return "Downloading: " + Math.round(progress * 100) + "%";
}

// Pure version of the download_* event handler in DownloadPage.
// entry: single model entry, event: string, payload: {progress}.
// Returns a new entry.
function applyDownloadEvent(entry, event, payload) {
    var next = {
        name: entry.name,
        filename: entry.filename,
        size: entry.size,
        description: entry.description,
        url: entry.url,
        progress: entry.progress,
        downloading: entry.downloading,
        paused: entry.paused,
        ready: entry.ready,
        requestId: entry.requestId,
        compatibility: entry.compatibility,
        compatibilityText: entry.compatibilityText
    };
    var p = payload || {};
    if (event === "download_progress") {
        next.progress = p.progress;
        next.downloading = true;
        next.paused = false;
    } else if (event === "download_paused") {
        next.progress = p.progress;
        next.downloading = false;
        next.paused = true;
    } else if (event === "download_complete") {
        next.progress = 1.0;
        next.downloading = false;
        next.paused = false;
        next.ready = true;
    } else if (event === "download_error") {
        next.downloading = false;
        next.paused = false;
        next.progress = 0.0;
    }
    return next;
}
