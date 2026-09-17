import QtQuick 2.7
import QtTest 1.2
import "../../qml/js/SettingsUtils.js" as SettingsUtils

TestCase {
    name: "SettingsUtils"

    function test_snapTemperature() {
        compare(SettingsUtils.snapTemperature(0.74), 0.7)
        compare(SettingsUtils.snapTemperature(0.75), 0.8)
        compare(SettingsUtils.snapTemperature(1.0), 1.0)
        compare(SettingsUtils.snapTemperature(0.1), 0.1)
    }

    function test_snapMaxTokens_small() {
        compare(SettingsUtils.snapMaxTokens(53), 50)
        compare(SettingsUtils.snapMaxTokens(57), 60)
        compare(SettingsUtils.snapMaxTokens(200), 200)
    }

    function test_snapMaxTokens_medium() {
        compare(SettingsUtils.snapMaxTokens(520), 500)
        compare(SettingsUtils.snapMaxTokens(530), 550)
    }

    function test_snapMaxTokens_large() {
        compare(SettingsUtils.snapMaxTokens(1200), 1000)
        compare(SettingsUtils.snapMaxTokens(1300), 1500)
        compare(SettingsUtils.snapMaxTokens(21000), 20000)
    }

    function test_getModelInfo_empty() {
        compare(SettingsUtils.getModelInfo([], ""), null)
        compare(SettingsUtils.getModelInfo([], null), null)
    }

    function test_getModelInfo_catalogHit_caseInsensitive() {
        var catalog = [
            { filename: "Qwen2.5-1.5B-Q4_K_M.gguf", maxContext: 32768, name: "Qwen" }
        ]
        var info = SettingsUtils.getModelInfo(catalog, "qwen2.5-1.5b-q4_k_m.gguf")
        compare(info.name, "Qwen")
        compare(info.maxContext, 32768)
    }

    function test_getModelInfo_fallback_qwen() {
        var info = SettingsUtils.getModelInfo([], "qwen2.5-1.5b-q4_k_m.gguf")
        compare(info.maxContext, 32768)
        compare(info.developer, "Alibaba Group")
    }

    function test_getModelInfo_fallback_tinyllama() {
        var info = SettingsUtils.getModelInfo([], "tinyllama-1.1b-chat.gguf")
        compare(info.maxContext, 2048)
    }

    function test_getModelInfo_fallback_unknown() {
        var info = SettingsUtils.getModelInfo([], "my-custom-model.gguf")
        compare(info.maxContext, 2048)
        compare(info.developer, "Unknown")
        compare(info.name, "my-custom-model.gguf")
    }

    function test_getModelInfo_llama32_ordering() {
        // llama-3.2-1b must win over the generic 3b check for 1b files
        var info = SettingsUtils.getModelInfo([], "llama-3.2-1b-instruct.gguf")
        compare(info.maxContext, 128000)
        verify(info.name.indexOf("1B") >= 0)
    }

    function test_maxTokensForModel_clamps() {
        var catalog = [{ filename: "tiny.gguf", maxContext: 2048 }]
        compare(SettingsUtils.maxTokensForModel(catalog, "tiny.gguf", 4096, 2048), 2048)
        compare(SettingsUtils.maxTokensForModel(catalog, "tiny.gguf", 512, 2048), 512)
        // Unknown model falls back to defaultLimit
        compare(SettingsUtils.maxTokensForModel([], "unknown.gguf", 5000, 2048), 2048)
    }
}
