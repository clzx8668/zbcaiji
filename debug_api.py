"""查看所有 API 响应（含错误信息）"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-proxy-server", "--no-sandbox"])
    page = browser.new_page()

    page.goto("https://www.ccgp-shandong.gov.cn/")
    page.wait_for_load_state("networkidle")

    result = page.evaluate("""async () => {
        const results = [];
        const payloads = [
            {keyword: '智慧校园', currentPage: 1, pageSize: 3},
            {keyWord: '智慧校园', currentPage: 1, pageSize: 3},
            {code: '智慧校园', currentPage: 1, pageSize: 3, colCode: '02'},
        ];
        
        for (const p of payloads) {
            const resp = await fetch('/api/website/site/searchAllByCode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(p)
            });
            const text = await resp.text();
            results.push({payload: Object.keys(p), status: resp.status, text: text});
        }
        return JSON.stringify(results, null, 2);
    }""")

    print(result[:3000])
    browser.close()
