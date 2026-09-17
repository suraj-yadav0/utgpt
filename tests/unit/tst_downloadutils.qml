import QtQuick 2.7
import QtTest 1.2
import "../../qml/js/DownloadUtils.js" as DownloadUtils

TestCase {
    name: "DownloadUtils"

    function sampleCatalog() {
        return [
            { name: "Qwen2.5 1.5B", filename: "qwen.gguf", size: "~1.0 GB",
              description: "multilingual chat", url: "https://x/qwen",
              developer: "Alibaba", usage: "coding",
              compatibility: "green", compatibilityText: "Highly Recommended" },
            { name: "TinyLlama 1.1B", filename: "tiny.gguf", size: "~700 MB",
              description: "fast chat", url: "https://x/tiny",
              developer: "Tiny", usage: "simple",
              compatibility: "yellow", compatibilityText: "Runs Fine" }
        ]
    }

    function sampleEntries() {
        return DownloadUtils.buildModelEntries(sampleCatalog(), "")
    }

    function test_filterEmpty_returnsAll() {
        compare(DownloadUtils.filterCatalog(sampleCatalog(), "").length, 2)
        compare(DownloadUtils.filterCatalog(sampleCatalog(), "   ").length, 2)
    }

    function test_filterByName() {
        var out = DownloadUtils.filterCatalog(sampleCatalog(), "qwen")
        compare(out.length, 1)
        compare(out[0].filename, "qwen.gguf")
    }

    function test_filterByDeveloper_caseInsensitive() {
        var out = DownloadUtils.filterCatalog(sampleCatalog(), "ALIBABA")
        compare(out.length, 1)
        compare(out[0].filename, "qwen.gguf")
    }

    function test_filterNoMatch() {
        compare(DownloadUtils.filterCatalog(sampleCatalog(), "nonexistent-model-xyz").length, 0)
    }

    function test_buildModelEntries_defaults() {
        var entries = DownloadUtils.buildModelEntries([{ name: "M", filename: "m.gguf" }], "")
        compare(entries.length, 1)
        compare(entries[0].progress, 0.0)
        verify(!entries[0].ready)
        verify(!entries[0].downloading)
        verify(!entries[0].paused)
        compare(entries[0].compatibility, "yellow")
    }

    function test_applyDownloadStates_ready() {
        var next = DownloadUtils.applyDownloadStates(sampleEntries(), {
            "qwen.gguf": { status: "ready" }
        })
        verify(next[0].ready)
        compare(next[0].progress, 1.0)
        verify(!next[1].ready)
        compare(next[1].progress, 0.0)
    }

    function test_applyDownloadStates_downloading_keepsRequestId() {
        var next = DownloadUtils.applyDownloadStates(sampleEntries(), {
            "tiny.gguf": { status: "downloading", requestId: "req-1" }
        })
        verify(next[1].downloading)
        verify(!next[1].paused)
        compare(next[1].requestId, "req-1")
    }

    function test_applyDownloadStates_paused() {
        var next = DownloadUtils.applyDownloadStates(sampleEntries(), {
            "tiny.gguf": { status: "paused", requestId: "req-2" }
        })
        verify(next[1].paused)
        verify(!next[1].downloading)
    }

    function test_applyDownloadStates_missingEntry_resets() {
        var entries = sampleEntries()
        entries[0].progress = 0.5
        entries[0].downloading = true
        var next = DownloadUtils.applyDownloadStates(entries, {})
        verify(!next[0].downloading)
        compare(next[0].progress, 0.0)
    }

    function test_applyDownloadStates_doesNotMutateInput() {
        var entries = sampleEntries()
        DownloadUtils.applyDownloadStates(entries, { "qwen.gguf": { status: "ready" } })
        verify(!entries[0].ready)
    }

    function test_downloadStatusLabel() {
        compare(DownloadUtils.downloadStatusLabel(0.0, true, false), "Connecting...")
        compare(DownloadUtils.downloadStatusLabel(0.5, true, false), "Downloading: 50%")
        compare(DownloadUtils.downloadStatusLabel(0.5, true, true), "Paused: 50%")
        compare(DownloadUtils.downloadStatusLabel(0.0, false, false), "")
    }

    function test_applyDownloadEvent_lifecycle() {
        var entry = sampleEntries()[0]
        var p1 = DownloadUtils.applyDownloadEvent(entry, "download_progress", { progress: 0.4 })
        verify(p1.downloading)
        compare(p1.progress, 0.4)

        var p2 = DownloadUtils.applyDownloadEvent(p1, "download_paused", { progress: 0.4 })
        verify(p2.paused)

        var done = DownloadUtils.applyDownloadEvent(p2, "download_complete", {})
        verify(done.ready)
        compare(done.progress, 1.0)

        var err = DownloadUtils.applyDownloadEvent(p1, "download_error", {})
        verify(!err.downloading)
        compare(err.progress, 0.0)
    }
}
