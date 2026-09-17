.pragma library

// Shared pure logic for ChatPage.qml.
// Kept UI-free so it can run under qmltestrunner (QtTest).

function isThinkingPlaceholder(text) {
    return text === "..." || text === "Thinking" ||
        (typeof text === "string" && text.indexOf("Thinking") === 0);
}

function isSaveableAssistantText(text) {
    return text !== "Thinking" && text !== "..." &&
        !(typeof text === "string" && text.indexOf("Thinking") === 0);
}

function formatAssistantText(currentText, chunk) {
    var base = currentText;
    if (base === "..." || (typeof base === "string" && base.indexOf("Thinking") === 0)) {
        base = "";
    }
    var newText = base + chunk;
    newText = newText.replace(/<think>\s*/gi, "*Thinking Process:*\n\n")
                     .replace(/\s*<\/think>\s*/gi, "\n\n---\n\n")
                     .replace(/<\|im_end\|>/gi, "")
                     .replace(/<\/im_end>/gi, "")
                     .replace(/<\|im_start\|>/gi, "")
                     .replace(/<end_of_turn>/gi, "")
                     .replace(/<start_of_turn>/gi, "")
                     .replace(/<\|end\|>/gi, "")
                     .replace(/<\|eot_id\|>/gi, "")
                     .replace(/<\|start_header_id\|>/gi, "")
                     .replace(/\[end of text\]/gi, "");
    return newText;
}

// messages: array of {role, text}. Returns history of {role, content},
// dropping Thinking/"..." assistant placeholders.
function buildHistory(messages) {
    var history = [];
    for (var i = 0; i < messages.length; i++) {
        var item = messages[i];
        if (item.role === "user") {
            history.push({ "role": item.role, "content": item.text });
        } else if (item.role === "assistant" && isSaveableAssistantText(item.text)) {
            history.push({ "role": item.role, "content": item.text });
        }
    }
    return history;
}

function shouldSaveAssistantMessage(role, text) {
    return role === "assistant" && isSaveableAssistantText(text);
}

// Duplicate-attach guard from ChatPage.attachDocument().
// Returns "duplicate-time", "in-flight", or "" (ok to proceed).
function attachGuard(fileUrl, lastUrl, lastTime, now, inFlight) {
    if (!fileUrl) {
        return "empty";
    }
    if (fileUrl === lastUrl && (now - lastTime) < 4000) {
        return "duplicate-time";
    }
    if (inFlight && inFlight[fileUrl]) {
        return "in-flight";
    }
    return "";
}

function fallbackResponseText(userStopped, errorMessage) {
    if (userStopped) {
        return "Generation stopped by user.";
    }
    if (errorMessage && errorMessage.length > 0) {
        return errorMessage;
    }
    return "The model stopped unexpectedly.";
}
