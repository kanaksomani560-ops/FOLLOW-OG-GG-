import os
from playwright.sync_api import sync_playwright

class BrowserManager:
    def __init__(self, extension_path=None):
        self.playwright = None
        self.browser_context = None
        self.extension_path = extension_path

    def parse_proxy(self, proxy_string):
        """Parse proxy string into Playwright proxy dict. Supports:
        - ip:port
        - user:pass@ip:port
        - http://user:pass@ip:port
        - ip:port:user:pass (alternative format)
        """
        if not proxy_string:
            return None
        
        proxy_string = proxy_string.strip().rstrip(".")
        if not proxy_string:
            return None
            
        if proxy_string.startswith("http://"):
            proxy_string = proxy_string[7:]
        elif proxy_string.startswith("https://"):
            proxy_string = proxy_string[8:]
        
        proxy_dict = {"server": ""}
        
        if "@" in proxy_string:
            auth, server = proxy_string.rsplit("@", 1)
            if ":" in auth:
                proxy_dict["username"], proxy_dict["password"] = auth.split(":", 1)
            proxy_dict["server"] = f"http://{server}"
        elif proxy_string.count(":") == 3:
            parts = proxy_string.split(":")
            host, port, user, password = parts[0], parts[1], parts[2], parts[3]
            proxy_dict["server"] = f"http://{host}:{port}"
            proxy_dict["username"] = user
            proxy_dict["password"] = password
        else:
            proxy_dict["server"] = f"http://{proxy_string}"
        
        return proxy_dict

    def start_browser(self, headless=False, proxy=None):
        self.playwright = sync_playwright().start()
        
        args = [
            "--disable-blink-features=AutomationControlled",
        ]

        extensions_to_load = []
        
        if self.extension_path:
            if not os.path.exists(self.extension_path):
                print(f"Warning: Extension path not found: {self.extension_path}")
            else:
                extensions_to_load.append(self.extension_path)

        ext_dir = os.path.join(os.getcwd(), "extensions")
        if os.path.exists(ext_dir):
            for item in os.listdir(ext_dir):
                if "Canvas" in item or "WebGL" in item:
                    continue
                    
                full_path = os.path.join(ext_dir, item)
                if os.path.isdir(full_path):
                    extensions_to_load.append(full_path)
        
        if extensions_to_load:
            paths = ",".join(extensions_to_load)
            args.append(f"--disable-extensions-except={paths}")
            args.append(f"--load-extension={paths}")
            print(f"Loaded {len(extensions_to_load)} extensions.")

        user_data_dir = os.path.join(os.getcwd(), "user_data")
        
        import random
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 OPR/124.0.0.0"
        ]
        selected_ua = random.choice(user_agents)
        print(f"Using User-Agent: {selected_ua}")

        proxy_config = self.parse_proxy(proxy)
        if proxy_config:
            print(f"Using Proxy: {proxy_config['server']}")

        self.browser_context = self.playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            args=args,
            viewport={"width": 1920, "height": 1080}, 
            user_agent=selected_ua,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            proxy=proxy_config,
            extra_http_headers={
                "Accept-Language": "fr-FR,fr;q=0.9"
            }
        )
        
        return self.browser_context

    def close(self):
        if self.browser_context:
            self.browser_context.close()
        if self.playwright:
            self.playwright.stop()

