"""Measure streamed projection, DOM continuity and scroll position in Chromium."""

import json
from playwright.sync_api import sync_playwright


SAMPLES = {
    "paragraph": "第一句。第二句继续说明。\n\n随后给出结论。",
    "blocks": "# 研判摘要\n\n- 第一项\n- 第二项\n\n```text\n逐行记录\n```\n\n结论。",
    "sources": "资料如下。\n\n| 记录摘要 | 来源 |\n| --- | --- |\n| 已查得三条记录 | [来源9](#source-long-id-123)、[来源10](#source-other-id-456) |\n\n表格之后的正文。",
}


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1000, "height": 800}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:19786/tests/answer-stability-harness.html")
    page.locator(".smooth-message-text .markdown").wait_for(state="attached")
    results = {}
    for name, sample in SAMPLES.items():
        page.reload()
        page.locator(".smooth-message-text .markdown").wait_for(state="attached")
        previous = ""
        previous_projection = ""
        regressions = []
        projection_regressions = []
        heights = []
        drops = []
        preserved = []
        for index, character in enumerate(sample):
            page.evaluate("value => window.answerHarness.setText(value)", sample[:index + 1])
            page.wait_for_timeout(35)
            state = page.locator(".smooth-message-text").evaluate("element => ({ text: element.querySelector('.markdown').textContent, height: element.getBoundingClientRect().height, nodes: element.querySelector('.markdown').childElementCount, pending: !!element.querySelector('.stream-table-pending') })")
            current = state["text"]
            projection = page.evaluate("() => window.answerHarness.snapshot().projection?.text || ''")
            if not current.startswith(previous):
                regressions.append({"at": index + 1, "before": previous[-60:], "after": current[-60:]})
            if name != "sources" and not projection.startswith(previous_projection):
                projection_regressions.append(index + 1)
            previous = current
            previous_projection = projection
            if heights and heights[-1] - state["height"] > 2:
                drops.append({"at": index + 1, "before": heights[-1], "after": state["height"], "pending": state["pending"]})
            heights.append(state["height"])
            if name == "sources" and sample[:index + 1].endswith("资料如下。\n\n"):
                page.evaluate("() => { window.firstParagraph = document.querySelector('.smooth-message-text .markdown p') }")
            if name == "sources" and sample[:index + 1].endswith("| --- | --- |\n"):
                page.evaluate("() => { window.firstTable = document.querySelector('.smooth-message-text table') }")
            if name == "sources" and sample[:index + 1].endswith("[来源9](#source-long-id-123)"):
                page.evaluate("() => { window.firstLink = document.querySelector('.smooth-message-text .source-link') }")
        page.evaluate("() => window.answerHarness.setComplete(true)")
        page.wait_for_timeout(100)
        final = page.locator(".smooth-message-text .markdown").inner_text()
        preserved = page.evaluate("() => ({ paragraph: !window.firstParagraph || window.firstParagraph === document.querySelector('.smooth-message-text .markdown p'), table: !window.firstTable || window.firstTable === document.querySelector('.smooth-message-text table'), link: !window.firstLink || window.firstLink === document.querySelector('.smooth-message-text .source-link') })")
        assert not drops, f"{name}: answer height shrank while text grew: {drops}"
        assert not projection_regressions, f"{name}: projected text regressed: {projection_regressions}"
        assert all(preserved.values()), f"{name}: completed DOM nodes were replaced: {preserved}"
        assert final.strip(), f"{name}: completed answer is empty"
        results[name] = {"raw_characters": len(sample), "visible_characters": page.evaluate("() => window.answerHarness.snapshot().visibleCharacters"), "projection_characters": len(page.evaluate("() => window.answerHarness.snapshot().projection?.text || ''")), "dom_serialization_changes": regressions[:3], "projection_regressions": projection_regressions, "height_drops": drops, "completed_nodes_preserved": preserved}
    page.evaluate("() => window.answerHarness.pauseFollow()")
    before_scroll = page.locator(".messages-scroll").evaluate("element => element.scrollTop")
    page.evaluate("value => window.answerHarness.setText(value)", SAMPLES["sources"] + "\n\n新的一段回答。")
    page.wait_for_timeout(100)
    assert page.locator(".messages-scroll").evaluate("element => element.scrollTop") == before_scroll
    page.reload()
    page.get_by_role("button", name="下一页").click()
    assert "事发地点" in page.locator(".question-incomplete").inner_text()
    assert page.get_by_role("button", name="提交回答").is_disabled()
    page.get_by_role("button", name="返回未答题").click()
    assert "事发地点" in page.locator(".question-page legend").inner_text()
    page.get_by_text("城区", exact=True).click()
    page.get_by_role("button", name="下一页").click()
    page.get_by_text("半径 500 米", exact=True).click()
    submit = page.get_by_role("button", name="提交回答")
    assert submit.is_enabled()
    submit.hover()
    hover = submit.evaluate("element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color })")
    assert hover == {"background": "rgb(9, 105, 218)", "color": "rgb(255, 255, 255)"}, hover
    page.evaluate("() => window.answerHarness.setBusy(true)")
    assert submit.is_disabled()
    assert submit.locator(".spinner").count() == 1
    page.evaluate("() => window.answerHarness.setBusy(false)")
    assert submit.is_enabled()
    results["question"] = {"incomplete_navigation": True, "submit_enabled_after_all_answers": True, "hover": hover, "busy_disables_submit": True}
    results["reader_scroll_preserved"] = True
    results["page_errors"] = errors
    print(json.dumps(results, ensure_ascii=False, indent=2))
    browser.close()
