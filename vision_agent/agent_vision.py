import json
import os
import base64
import sqlite3
import csv
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(PROJECT_DIR, "samples")
DB_PATH = os.path.join(PROJECT_DIR, "products.db")

BANNER = """
{sep}
   🤖  ВИДЕО-АГЕНТ РАСПОЗНАВАНИЯ ТОВАРОВ
      Vision Product Recognition Agent v1.0
{sep}
""".format(sep="=" * 66)

AGENT_NAME = "Vision Product Recognition Agent"


class VisionProductAgent:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("API key not found. Set API_KEY in .env file or pass as argument.")

        self.base_url = os.getenv("BASE_URL", "https://openrouter.ai/api/v1")
        self.model = model or os.getenv("MODEL", "qwen3-vl-flash")

        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                brand TEXT,
                model_name TEXT,
                category TEXT,
                price REAL,
                currency TEXT,
                color TEXT,
                material TEXT,
                dimensions TEXT,
                weight TEXT,
                specs TEXT,
                description TEXT,
                raw_response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _get_processed_filenames(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT filename FROM products")
        filenames = {row[0] for row in cursor.fetchall()}
        conn.close()
        return filenames

    def _encode_image(self, image_path):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _detect_image_type(self, image_path):
        ext = Path(image_path).suffix.lower()
        return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(ext, "jpeg")

    def analyze_product(self, image_path):
        print(f"\n  {Path(image_path).name}")

        b64 = self._encode_image(image_path)
        img_type = self._detect_image_type(image_path)
        data_url = f"data:image/{img_type};base64,{b64}"

        prompt = """You are a product recognition assistant. Analyze this product image and extract information in JSON format only, no other text.

{
  "brand": "brand name or null",
  "model_name": "model name/number or null",
  "category": "product category (laptop, phone, shoe, bottle, etc)",
  "price": 0.0,
  "currency": "USD or null",
  "color": "main color or null",
  "material": "material if visible or null",
  "dimensions": "size info if visible or null",
  "weight": "weight if visible or null",
  "specs": "key specifications as a string",
  "description": "one-line product description"
}

If you see a price tag or label, extract the price. If you see a barcode or SKU, include it in specs. Return ONLY valid JSON, no markdown."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)

            data["filename"] = Path(image_path).name
            data["raw_response"] = content
            return data

        except Exception as e:
            print(f"    Error: {e}")
            return {"filename": Path(image_path).name, "error": str(e)}

    def save_product(self, data):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO products
                (filename, brand, model_name, category, price, currency,
                 color, material, dimensions, weight, specs, description, raw_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("filename"),
            data.get("brand"),
            data.get("model_name"),
            data.get("category"),
            data.get("price"),
            data.get("currency"),
            data.get("color"),
            data.get("material"),
            data.get("dimensions"),
            data.get("weight"),
            data.get("specs"),
            data.get("description"),
            data.get("raw_response"),
        ))
        conn.commit()
        product_id = cursor.lastrowid
        conn.close()
        return product_id

    def process_image(self, image_path):
        if not os.path.exists(image_path):
            print(f"  File not found: {image_path}")
            return None

        data = self.analyze_product(image_path)
        if "error" in data and not data.get("brand"):
            return data

        pid = self.save_product(data)
        print(f"    Saved to DB (ID: {pid})")
        return data

    def process_directory(self, directory_path):
        exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        all_files = sorted([
            f for f in os.listdir(directory_path)
            if Path(f).suffix.lower() in exts
        ])

        processed = self._get_processed_filenames()
        new_files = [f for f in all_files if f not in processed]

        if not new_files:
            print("\n  No new images to process.")
            return []

        skipped = len(all_files) - len(new_files)
        print(f"\n  Found {len(new_files)} new image(s)", end="")
        if skipped:
            print(f" ({skipped} already processed, skipped)", end="")
        print()

        results = []
        for i, fname in enumerate(new_files, 1):
            fpath = os.path.join(directory_path, fname)
            print(f"\n  [{i}/{len(new_files)}]", end="")
            data = self.process_image(fpath)
            if data:
                results.append(data)

        if results:
            self.export_csv()
        return results

    def export_csv(self, output_path=None):
        if not output_path:
            output_path = os.path.join(PROJECT_DIR, "products.csv")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY id ASC")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow(row)

        conn.close()
        print(f"  Exported to {output_path}")
        return output_path

    def show_table(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, filename, brand, model_name, category, price, currency, color, specs, created_at
            FROM products ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print("  No products in database.")
            return

        print(f"\n{'ID':<4} {'File':<40} {'Brand':<14} {'Model':<22} {'Category':<14} {'Price':<9} {'Color':<14} {'Specs'}")
        print("-" * 160)
        for r in rows:
            price = f"{r[5]:.2f} {r[6] or ''}" if r[5] else ""
            specs = (r[8] or '')[:40]
            fname = (str(r[1])[:37] + '...') if len(str(r[1])) > 40 else str(r[1])
            print(f"{r[0]:<4} {fname:<40} {str(r[2] or ''):<14} {str(r[3] or ''):<22} {str(r[4] or ''):<14} {price:<9} {str(r[7] or ''):<14} {specs}")

    def show_detail(self, product_id=None):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if product_id:
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        else:
            cursor.execute("SELECT * FROM products ORDER BY id DESC LIMIT 1")

        row = cursor.fetchone()
        conn.close()

        if not row:
            print("  Product not found.")
            return

        print(f"\n{'='*60}")
        for k in row.keys():
            val = row[k]
            if val:
                print(f"  {k}: {val}")
        print(f"{'='*60}")

    def generate_report(self, output_path=None):
        if not output_path:
            output_path = os.path.join(PROJECT_DIR, "report.html")

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print("  No products in database.")
            return

        cards = ""
        for r in rows:
            price = f"{r['price']:.2f} {r['currency']}" if r['price'] else ""
            specs = (r['specs'] or '').replace('\n', '<br>')
            desc = r['description'] or ''
            material = r['material'] or ''
            dimensions = r['dimensions'] or ''
            weight = r['weight'] or ''
            color = r['color'] or ''
            raw = r['raw_response'] or ''

            cards += f"""
            <div class="card">
                <div class="card-header">
                    <span class="id">#{r['id']}</span>
                    <span class="date">{r['created_at']}</span>
                </div>
                <div class="card-body">
                    <div class="field"><span class="label">File</span> {r['filename']}</div>
                    <div class="field"><span class="label">Brand</span> {r['brand'] or '-'}</div>
                    <div class="field"><span class="label">Model</span> {r['model_name'] or '-'}</div>
                    <div class="field"><span class="label">Category</span> {r['category'] or '-'}</div>
                    <div class="field"><span class="label">Price</span> {price or '-'}</div>
                    <div class="field"><span class="label">Color</span> {color or '-'}</div>
                    <div class="field"><span class="label">Material</span> {material or '-'}</div>
                    <div class="field"><span class="label">Dimensions</span> {dimensions or '-'}</div>
                    <div class="field"><span class="label">Weight</span> {weight or '-'}</div>
                    <div class="field"><span class="label">Specs</span> {specs or '-'}</div>
                    <div class="field"><span class="label">Description</span> {desc}</div>
                    <details>
                        <summary>Raw Response</summary>
                        <pre>{raw}</pre>
                    </details>
                </div>
            </div>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Products Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 30px; }}
h1 {{ color: #fff; margin-bottom: 10px; font-size: 24px; }}
.sub {{ color: #888; margin-bottom: 30px; }}
.card {{ background: #1a1a2e; border-radius: 12px; margin-bottom: 20px; overflow: hidden; border: 1px solid #2a2a4a; }}
.card-header {{ display: flex; justify-content: space-between; padding: 14px 20px; background: #16213e; border-bottom: 1px solid #2a2a4a; }}
.id {{ color: #00d4ff; font-weight: bold; }}
.date {{ color: #666; font-size: 13px; }}
.card-body {{ padding: 16px 20px; }}
.field {{ padding: 5px 0; border-bottom: 1px solid #1f1f3a; font-size: 14px; }}
.field:last-child {{ border: none; }}
.label {{ color: #888; display: inline-block; width: 110px; font-weight: 600; }}
details {{ margin-top: 10px; }}
summary {{ cursor: pointer; color: #00d4ff; font-size: 13px; }}
pre {{ background: #0a0a1a; padding: 12px; border-radius: 8px; margin-top: 8px; font-size: 12px; overflow-x: auto; color: #8f8; }}
</style>
</head>
<body>
<h1>Products Report</h1>
<div class="sub">{len(rows)} product(s)</div>
{cards}
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"  Report saved: {output_path}")
        return output_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Vision Product Recognition Agent")
    parser.add_argument("--api-key", help="API key (or set API_KEY in .env)")
    parser.add_argument("--model", default=None, help="Vision model (default: from .env or qwen3-vl-flash)")
    parser.add_argument("--dir", help="Directory with images to process")
    parser.add_argument("--image", help="Single image to process")
    parser.add_argument("--show", action="store_true", help="Show products table")
    parser.add_argument("--detail", nargs="?", const=True, type=int, help="Show full product details (optional ID)")
    parser.add_argument("--export", nargs="?", const=True, help="Export to CSV (optional path)")
    parser.add_argument("--report", nargs="?", const=True, help="Generate HTML report (optional path)")

    args = parser.parse_args()

    print(BANNER)

    try:
        agent = VisionProductAgent(api_key=args.api_key, model=args.model)
    except ValueError as e:
        print(f"Error: {e}")
        print("\nCreate a .env file in this folder with:")
        print("  API_KEY=sk-...")
        print("  BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        print("  MODEL=qwen2.5-vl-72b-instruct")
        print("\nGet API key at: https://modelstudio.console.alibabacloud.com")
        return

    if args.dir:
        agent.process_directory(args.dir)
    elif args.image:
        agent.process_image(args.image)
    elif args.show:
        agent.show_table()
        return
    elif args.detail:
        pid = args.detail if isinstance(args.detail, int) else None
        agent.show_detail(pid)
        return
    elif args.export:
        path = args.export if isinstance(args.export, str) else None
        agent.export_csv(path)
    elif args.report:
        path = args.report if isinstance(args.report, str) else None
        report_path = agent.generate_report(path)
        if report_path:
            os.system(f"open '{report_path}'")
    else:
        print("No action. Use --dir, --image, --show, --detail, --report, or --export")

    agent.show_table()


if __name__ == "__main__":
    main()
