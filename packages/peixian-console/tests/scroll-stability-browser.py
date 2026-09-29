"""Exercise the production chat scroll controller across layout and content changes."""

import json
from playwright.sync_api import sync_playwright


def settle(page):
    page.wait_for_timeout(90)
    return page.evaluate("() => window.scrollHarness.snapshot()")


def bottom(state):
    return abs(state["scrollTop"] - max(0, state["scrollHeight"] - state["clientHeight"])) <= 1


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:19786/tests/scroll-stability-harness.html")
    page.wait_for_function("window.scrollHarness?.measures?.length > 0")
    states = {"short": settle(page)}
    page.evaluate("() => window.scrollHarness.setCount(8)")
    states["overflow"] = settle(page)
    assert states["overflow"]["scrollHeight"] > states["overflow"]["clientHeight"]
    assert bottom(states["overflow"])
    page.evaluate("() => window.scrollHarness.setLast('末尾内容。'.repeat(70))")
    states["streaming"] = settle(page)
    assert bottom(states["streaming"])
    page.evaluate("() => window.scrollHarness.setCard('警情关联半径')")
    states["card_added"] = settle(page)
    assert states["card_added"]["clientHeight"] == states["streaming"]["clientHeight"]
    assert bottom(states["card_added"])
    page.evaluate("() => window.scrollHarness.setCard('警情关联半径，补充更长的说明和选项。'.repeat(5))")
    states["card_changed"] = settle(page)
    assert states["card_changed"]["clientHeight"] == states["card_added"]["clientHeight"]
    assert bottom(states["card_changed"])
    page.evaluate("() => window.scrollHarness.setCard('')")
    states["card_removed"] = settle(page)
    assert bottom(states["card_removed"])
    page.evaluate("() => window.scrollHarness.readUp()")
    states["reading"] = settle(page)
    assert not states["reading"]["following"]
    page.evaluate("() => { const box = document.querySelector('.messages-scroll').getBoundingClientRect(); window.readAnchor = Array.from(document.querySelectorAll('.markdown p')).find(item => item.getBoundingClientRect().bottom > box.top + 1); window.readOffset = window.readAnchor.getBoundingClientRect().top - box.top }")
    page.evaluate("() => window.scrollHarness.setFirst('较早的内容。'.repeat(120))")
    states["upper_grew"] = settle(page)
    offset = page.evaluate("() => window.readAnchor.getBoundingClientRect().top - document.querySelector('.messages-scroll').getBoundingClientRect().top - window.readOffset")
    assert abs(offset) <= 1, f"reading anchor drifted {offset}px"
    assert not states["upper_grew"]["following"]
    page.evaluate("() => window.scrollHarness.setLast('末尾内容。'.repeat(100))")
    states["lower_grew"] = settle(page)
    assert abs(states["lower_grew"]["scrollTop"] - states["upper_grew"]["scrollTop"]) <= 1
    page.evaluate("() => window.scrollHarness.setCard('阅读历史时出现的追问卡片')")
    states["reading_card"] = settle(page)
    assert abs(states["reading_card"]["scrollTop"] - states["lower_grew"]["scrollTop"]) <= 1
    page.evaluate("() => window.scrollHarness.setCard('')")
    assert abs(settle(page)["scrollTop"] - states["reading_card"]["scrollTop"]) <= 1
    page.set_viewport_size({"width": 1000, "height": 550})
    states["reading_resize"] = settle(page)
    assert not states["reading_resize"]["following"]
    page.evaluate("() => window.scrollHarness.resume()")
    states["resumed"] = settle(page)
    assert states["resumed"]["following"] and bottom(states["resumed"])
    page.evaluate("() => window.scrollHarness.setComposerHeight(170)")
    states["composer_grew"] = settle(page)
    assert bottom(states["composer_grew"])
    page.set_viewport_size({"width": 420, "height": 550})
    states["narrow"] = settle(page)
    assert bottom(states["narrow"])
    page.evaluate("() => window.scrollHarness.setCount(9)")
    states["next_round"] = settle(page)
    assert bottom(states["next_round"])
    measures = page.evaluate("() => window.scrollHarness.measures")
    assert not errors, errors
    print(json.dumps({"states": states, "sources": sorted(set(item["source"] for item in measures)), "writes": sum(abs(item["after"]["scrollTop"] - item["before"]["scrollTop"]) > 0.5 for item in measures), "page_errors": errors}, ensure_ascii=False, indent=2))
    browser.close()
