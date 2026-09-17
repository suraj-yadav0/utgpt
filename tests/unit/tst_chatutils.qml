import QtQuick 2.7
import QtTest 1.2
import "../../qml/js/ChatUtils.js" as ChatUtils

TestCase {
    name: "ChatUtils"

    function test_isThinkingPlaceholder() {
        verify(ChatUtils.isThinkingPlaceholder("Thinking"))
        verify(ChatUtils.isThinkingPlaceholder("Thinking..."))
        verify(ChatUtils.isThinkingPlaceholder("..."))
        verify(!ChatUtils.isThinkingPlaceholder("Hello"))
        verify(!ChatUtils.isThinkingPlaceholder(""))
        verify(!ChatUtils.isThinkingPlaceholder("Thinking Process: done"))
    }

    function test_formatAppendsChunk() {
        compare(ChatUtils.formatAssistantText("", "Hello"), "Hello")
        compare(ChatUtils.formatAssistantText("Hi ", "there"), "Hi there")
    }

    function test_formatResetsThinkingPlaceholder() {
        compare(ChatUtils.formatAssistantText("Thinking", "Hi"), "Hi")
        compare(ChatUtils.formatAssistantText("Thinking...", "Hi"), "Hi")
        compare(ChatUtils.formatAssistantText("...", "Hi"), "Hi")
    }

    function test_formatStripsThinkTags() {
        var out = ChatUtils.formatAssistantText("", "<think>reasoning</think>answer")
        verify(out.indexOf("<think>") < 0)
        verify(out.indexOf("</think>") < 0)
        verify(out.indexOf("Thinking Process") >= 0)
        verify(out.indexOf("answer") >= 0)
    }

    function test_formatStripsControlTokens() {
        var out = ChatUtils.formatAssistantText("", "hi<|im_end|>there<|eot_id|>end[end of text]")
        compare(out, "hithereend")
    }

    function test_buildHistoryFiltersPlaceholders() {
        var history = ChatUtils.buildHistory([
            { role: "user", text: "hello" },
            { role: "assistant", text: "Thinking" },
            { role: "assistant", text: "..." },
            { role: "assistant", text: "Thinking..." },
            { role: "assistant", text: "real answer" }
        ])
        compare(history.length, 2)
        compare(history[0].content, "hello")
        compare(history[1].content, "real answer")
    }

    function test_buildHistoryEmpty() {
        compare(ChatUtils.buildHistory([]).length, 0)
    }

    function test_shouldSaveAssistantMessage() {
        verify(ChatUtils.shouldSaveAssistantMessage("assistant", "hello"))
        verify(!ChatUtils.shouldSaveAssistantMessage("assistant", "Thinking"))
        verify(!ChatUtils.shouldSaveAssistantMessage("assistant", "Thinking..."))
        verify(!ChatUtils.shouldSaveAssistantMessage("assistant", "..."))
        verify(!ChatUtils.shouldSaveAssistantMessage("user", "hello"))
    }

    function test_attachGuard() {
        compare(ChatUtils.attachGuard("", "", 0, 1000, {}), "empty")
        compare(ChatUtils.attachGuard("file:///a", "file:///a", 900, 1000, {}), "duplicate-time")
        // Outside the 4s window it is allowed again
        compare(ChatUtils.attachGuard("file:///a", "file:///a", 0, 5000, {}), "")
        compare(ChatUtils.attachGuard("file:///a", "file:///b", 0, 1000, { "file:///a": true }), "in-flight")
        compare(ChatUtils.attachGuard("file:///a", "file:///b", 0, 1000, {}), "")
    }

    function test_fallbackResponseText() {
        compare(ChatUtils.fallbackResponseText(true, "boom"), "Generation stopped by user.")
        compare(ChatUtils.fallbackResponseText(false, "boom"), "boom")
        compare(ChatUtils.fallbackResponseText(false, ""), "The model stopped unexpectedly.")
    }
}
