import cv2
import pytesseract
from PIL import Image
import numpy as np
import re
from typing import Dict, Any, List, Tuple
import os
from pdf2image import convert_from_path
from PyPDF2 import PdfReader
import tempfile

class DocumentExtractor:
    """Класс для извлечения данных из изображений документов"""
    
    def __init__(self):
        self.document_type = None
        self.raw_text = None
    
    def extract_from_image(self, image_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Извлечение данных из изображения документа или PDF
        
        Args:
            image_path: путь к файлу изображения или PDF
            
        Returns:
            Кортеж (тип документа, извлеченные данные)
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Файл не найден: {image_path}")
        
        # Проверяем, является ли это PDF
        if image_path.lower().endswith('.pdf'):
            return self._extract_from_pdf(image_path)
        
        # Загружаем изображение
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Не удалось загрузить изображение: {image_path}")
        
        # Предварительная обработка изображения
        processed_image = self._preprocess_image(image)
        
        # Извлекаем текст
        self.raw_text = pytesseract.image_to_string(processed_image, lang='eng+rus')
        
        # Определяем тип документа
        self.document_type = self._detect_document_type(self.raw_text)
        
        # Извлекаем структурированные данные
        extracted_data = self._extract_by_type(self.document_type)
        
        print(f"✓ Тип документа определен: {self.document_type}")
        
        return self.document_type, extracted_data
    
    def _preprocess_image(self, image) -> np.ndarray:
        """Предварительная обработка изображения для улучшения OCR"""
        # Преобразуем в оттенки серого
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Применяем пороговую обработку
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # Удаляем шум
        denoised = cv2.fastNlMeansDenoising(binary, h=10)
        
        # Масштабируем изображение для лучшего распознавания
        scale_factor = 2
        scaled = cv2.resize(denoised, None, fx=scale_factor, fy=scale_factor, 
                           interpolation=cv2.INTER_CUBIC)
        
        return scaled
    
    def _detect_document_type(self, text: str) -> str:
        """Определение типа документа на основе текста"""
        text_lower = text.lower()
        
        # Ключевые слова для определения типа документа
        bl_keywords = ['bill of lading', 'bol', 'b/l', 'коносамент',
                       'shipper signature', 'carrier signature', 'carrier information',
                       'port of loading', 'port of discharge', 'vessel', 'voyage',
                       'pro number', 'freight charge']
        invoice_keywords = ['invoice', 'инвойс', 'счет-фактура', 'amount due',
                           'total amount', 'currency', 'supplier', 'buyer']
        packing_keywords = ['packing list', 'пакинг лист', 'упаковочный лист',
                           'contents', 'package', 'weight', 'volume']
        
        bl_count = sum(1 for kw in bl_keywords if kw in text_lower)
        invoice_count = sum(1 for kw in invoice_keywords if kw in text_lower)
        packing_count = sum(1 for kw in packing_keywords if kw in text_lower)
        
        # Bill of Lading имеет приоритет, если найдено достаточно ключевых слов
        if bl_count >= 3:
            return "bill_of_lading"
        elif invoice_count > max(bl_count, packing_count):
            return "invoice"
        elif packing_count > max(bl_count, invoice_count):
            return "packing_list"
        else:
            # По умолчанию, если есть хоть какие-то признаки BL
            if bl_count >= 1:
                return "bill_of_lading"
            return "unknown"
    
    def _extract_by_type(self, doc_type: str) -> Dict[str, Any]:
        """Извлечение данных в зависимости от типа документа"""
        if doc_type == "bill_of_lading":
            return self._extract_bill_of_lading()
        elif doc_type == "invoice":
            return self._extract_invoice()
        elif doc_type == "packing_list":
            return self._extract_packing_list()
        else:
            return {"raw_text": self.raw_text}
    
    def _extract_bill_of_lading(self) -> Dict[str, Any]:
        """Извлечение данных из коносамента"""
        data = {
            "document_type": "bill_of_lading",
            "raw_text": self.raw_text
        }
        
        text = self.raw_text
        lines = text.split('\n')
        
        # Извлекаем BL номер
        bl_match = re.search(r'(?:BL\s+Number|B/L|Bill\s*of\s*Lading\s*Number)[\s:]*([A-Z0-9\-\/]*\d+[A-Z0-9\-\/]*)', text, re.IGNORECASE)
        if not bl_match:
            bl_match = re.search(r'(?:BL|B/L)[\s:]*([A-Z0-9\-\/]*\d+[A-Z0-9\-\/]*)', text, re.IGNORECASE)
        data['bl_number'] = bl_match.group(1).strip() if bl_match else None
        
        # Функция для извлечения информации из блока с несколькими строками
        def extract_block_info(block_text):
            """Извлекает имя, адрес, город из блока текста"""
            block_lines = [l.strip() for l in block_text.strip().split('\n') if l.strip()]
            
            name = None
            address = None
            city_state_zip = None
            
            if len(block_lines) > 0:
                name = block_lines[0]
            if len(block_lines) > 1:
                address = block_lines[1]
            if len(block_lines) > 2:
                city_state_zip = block_lines[2]
            
            return name, address, city_state_zip
        
        # Извлекаем информацию о грузоотправителе
        shipper_section = self._extract_section(text, ['Shipper:', 'SHIPPER:', 'SHIPPER / EXPORTER'], ['Carrier', 'CARRIER', 'Consignee', 'CONSIGNEE'])
        if shipper_section:
            s_name, s_addr, s_city = extract_block_info(shipper_section)
            data['shipper_name'] = s_name
            data['shipper_address'] = s_addr
            data['shipper_city_state_zip'] = s_city
        else:
            # Простой парсинг
            shipper_match = re.search(r'(?:Shipper|SHIPPER\s*(?:/\s*EXPORTER)?)[\s:]*\n+\s*([^\n]+)\n\s*([^\n]*)\n\s*([^\n]*)', text, re.IGNORECASE | re.MULTILINE)
            if shipper_match:
                data['shipper_name'] = shipper_match.group(1).strip()
                data['shipper_address'] = shipper_match.group(2).strip()
                data['shipper_city_state_zip'] = shipper_match.group(3).strip()
        
        # Извлекаем информацию о грузополучателе
        consignee_section = self._extract_section(text, ['Consignee:', 'CONSIGNEE:', 'CONSIGNEE'], ['Notify', 'NOTIFY', 'Port', 'PORT', 'NOTIFY PARTY', 'CONTAINERS'])
        if consignee_section:
            c_name, c_addr, c_city = extract_block_info(consignee_section)
            data['consignee_name'] = c_name
            data['consignee_address'] = c_addr
            data['consignee_city_state_zip'] = c_city
        else:
            # Простой парсинг
            consignee_match = re.search(r'(?:Consignee|CONSIGNEE)[\s:]*\n+\s*([^\n]+)\n\s*([^\n]*)\n\s*([^\n]*)', text, re.IGNORECASE | re.MULTILINE)
            if consignee_match:
                data['consignee_name'] = consignee_match.group(1).strip()
                data['consignee_address'] = consignee_match.group(2).strip()
                data['consignee_city_state_zip'] = consignee_match.group(3).strip()
        
        # Уведомить сторону
        notify_match = re.search(r'(?:Notify\s+Party|NOTIFY\s+PARTY|Notify|NOTIFY)[\s:]*\n+\s*([^\n]+)', text, re.IGNORECASE)
        if not notify_match:
            notify_match = re.search(r'(?:Notify|NOTIFY)[\s:]*\n+\s*([^\n]+)', text, re.IGNORECASE)
        data['notify_party'] = notify_match.group(1).strip() if notify_match else None
        
        # Порт отправления
        port_loading = re.search(r'(?:Port of Loading|PORT OF LOADING)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['port_of_loading'] = port_loading.group(1).strip() if port_loading else None
        
        # Порт назначения
        port_discharge = re.search(r'(?:Port of Discharge|PORT OF DISCHARGE)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['port_of_discharge'] = port_discharge.group(1).strip() if port_discharge else None
        
        # Название судна
        vessel_match = re.search(r'(?:Vessel|VESSEL)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['vessel_name'] = vessel_match.group(1).strip() if vessel_match else None
        
        # Номер рейса
        voyage_match = re.search(r'(?:Voyage\s+Number|VOYAGE\s+NUMBER|Voyage|VOYAGE)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['voyage_number'] = voyage_match.group(1).strip() if voyage_match else None
        
        # Pro number
        pro_match = re.search(r'(?:Pro\s+Number|PRO\s+NUMBER|Pro number|PRO\s*#)[\s:]*([A-Z0-9\-]+)', text, re.IGNORECASE)
        data['pro_number'] = pro_match.group(1).strip() if pro_match else None
        
        # Контейнеры
        container_matches = re.findall(r'([A-Z]{4}\d{7})', text)
        data['container_numbers'] = list(set(container_matches)) if container_matches else []
        data['total_containers'] = len(data['container_numbers'])
        
        # Общее количество мест
        packages_match = re.search(r'(?:#PKGS|#Packages|Total\s+Packages)[\s:]*(\d+)', text, re.IGNORECASE)
        if packages_match:
            data['total_packages'] = int(packages_match.group(1))
        
        # Общий вес
        weight_match = re.search(r'(?:GRAND TOTAL.*?WEIGHT|Total\s+Weight)[\s:]*(\d+[\.,]?\d*)', text, re.IGNORECASE | re.DOTALL)
        if weight_match and weight_match.group(1).strip():
            try:
                data['weight'] = float(weight_match.group(1).replace(',', '.'))
            except:
                pass
        
        # Дата
        date_match = re.search(r'(?:Date)[:\s]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})', text, re.IGNORECASE)
        data['date'] = date_match.group(1) if date_match else None
        
        # Дата pickup
        pickup_match = re.search(r'(?:Pickup\s+Date|PICKUP\s+DATE)[\s:]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})', text, re.IGNORECASE)
        data['pickup_date'] = pickup_match.group(1) if pickup_match else None
        
        # Условия фрейта
        freight_match = re.search(r'(?:Freight\s+Charge\s+Terms|FREIGHT\s+CHARGE\s+TERMS)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['freight_charge_terms'] = freight_match.group(1).strip() if freight_match else None
        
        # Специальные инструкции
        special_match = re.search(r'(?:Special\s+Instructions|SPECIAL\s+INSTRUCTIONS)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['special_instructions'] = special_match.group(1).strip() if special_match else None
        
        # Описание товара
        commodity_match = re.search(r'(?:Commodity|COMMODITY)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['commodity'] = commodity_match.group(1).strip() if commodity_match else None
        
        return data
    
    def _extract_invoice(self) -> Dict[str, Any]:
        """Извлечение данных из инвойса"""
        data = {
            "document_type": "invoice",
            "raw_text": self.raw_text
        }
        
        text = self.raw_text
        
        # Номер инвойса
        invoice_match = re.search(r'(?:Invoice\s+Number|Инвойс\s+(?:№|Номер)|No\.|№)[:\s]+([A-Z0-9\-\/]+)', text, re.IGNORECASE)
        data['invoice_number'] = invoice_match.group(1).strip() if invoice_match else None
        
        # Дата инвойса
        date_match = re.search(r'(?:Date|Дата)[:\s]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})', text, re.IGNORECASE)
        data['invoice_date'] = date_match.group(1) if date_match else None
        
        # Поставщик (ищем на следующей строке после Supplier/From)
        supplier_match = re.search(r'(?:Supplier|From|Поставщик|От)\s*(?:\/\s*From\s*)?[:\s]*\n\s*([^\n]+)', text, re.IGNORECASE)
        if not supplier_match:
            supplier_match = re.search(r'(?:Supplier|From|Поставщик|От)[:\s]*([^\n]+)', text, re.IGNORECASE)
        data['supplier'] = supplier_match.group(1).strip() if supplier_match else None
        
        # Покупатель (ищем на следующей строке после Buyer/To)
        buyer_match = re.search(r'(?:Buyer|To|Bill to|Покупатель|На)\s*(?:\/\s*To\s*)?[:\s]*\n\s*([^\n]+)', text, re.IGNORECASE)
        if not buyer_match:
            buyer_match = re.search(r'(?:Buyer|To|Bill to|Покупатель|На)[:\s]*([^\n]+)', text, re.IGNORECASE)
        data['buyer'] = buyer_match.group(1).strip() if buyer_match else None
        
        # Валюта
        currency_match = re.search(r'(?:Currency|Валюта)[:\s]*([A-Z]{3})', text, re.IGNORECASE)
        data['currency'] = currency_match.group(1) if currency_match else 'USD'
        
        # Общая сумма
        amount_match = re.search(r'(?:Total\s*(?:Amount)?|Итого|Grand\s*Total)[\s\(][^\)]*\)[:\s]*[\$€£]?\s*(\d+[\.,]\d{2})', text, re.IGNORECASE)
        if not amount_match:
            amount_match = re.search(r'(?:Total|Итого|Amount|Сумма)[\s:]*[\$€£]?\s*(\d+[\.,]\d{2})', text, re.IGNORECASE)
        if amount_match:
            data['total_amount'] = float(amount_match.group(1).replace(',', '.'))
        
        # Налог
        tax_match = re.search(r'Total\s*(?:Tax|VAT)[\s\(][^\)]*\)[:\s]*[\$€£]?\s*(\d+[\.,]\d{2})', text, re.IGNORECASE)
        if not tax_match:
            tax_match = re.search(r'(?:Tax|VAT|НДС|Налог)[\s:]*[\$€£]?\s*(\d+[\.,]\d{2})', text, re.IGNORECASE)
        if tax_match:
            data['tax'] = float(tax_match.group(1).replace(',', '.'))
        
        # Условия оплаты
        payment_match = re.search(r'(?:Payment Terms|Условия оплаты)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['payment_terms'] = payment_match.group(1).strip() if payment_match else None
        
        # Позиции (товары)
        data['items'] = self._extract_line_items(text)
        
        return data
    
    def _extract_packing_list(self) -> Dict[str, Any]:
        """Извлечение данных из пакинг листа"""
        data = {
            "document_type": "packing_list",
            "raw_text": self.raw_text
        }
        
        text = self.raw_text
        
        # Номер пакинг листа
        pl_match = re.search(r'(?:Packing List|Пакинг лист|P/L|PL)[\s:]*([A-Z0-9\-\/]+)', text, re.IGNORECASE)
        data['packing_list_number'] = pl_match.group(1).strip() if pl_match else None
        
        # Дата
        date_match = re.search(r'(?:Date|Дата)[\s:]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})', text, re.IGNORECASE)
        data['date'] = date_match.group(1) if date_match else None
        
        # Грузоотправитель
        shipper_match = re.search(r'(?:Shipper|Отправитель)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['shipper'] = shipper_match.group(1).strip() if shipper_match else None
        
        # Грузополучатель
        consignee_match = re.search(r'(?:Consignee|Получатель)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['consignee'] = consignee_match.group(1).strip() if consignee_match else None
        
        # Количество мест
        packages_match = re.search(r'(?:Total Packages|Всего мест)[\s:]*(\d+)', text, re.IGNORECASE)
        if packages_match:
            data['total_packages'] = int(packages_match.group(1))
        
        # Общий вес
        weight_match = re.search(r'(?:Total Weight|Общий вес)[\s:]*(\d+[\.,]\d+)\s*(?:kg|кг|MT|т)', text, re.IGNORECASE)
        if weight_match:
            data['total_weight'] = float(weight_match.group(1).replace(',', '.'))
        
        # Общий объем
        volume_match = re.search(r'(?:Total Volume|Общий объем)[\s:]*(\d+[\.,]\d+)\s*(?:cbm|м3|m3)', text, re.IGNORECASE)
        if volume_match:
            data['total_volume'] = float(volume_match.group(1).replace(',', '.'))
        
        # Описание
        desc_match = re.search(r'(?:Description|Описание)[\s:]*([^\n]+)', text, re.IGNORECASE)
        data['description'] = desc_match.group(1).strip() if desc_match else None
        
        # Позиции товаров
        data['items'] = self._extract_line_items(text)
        
        return data
    
    def _extract_line_items(self, text: str) -> List[Dict[str, Any]]:
        """Извлечение позиций товаров из текста"""
        items = []
        lines = text.split('\n')

        # Ищем табличную часть: строка начинается с названия товара, затем QTY, цена
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Пропускаем заголовки и итоги
            if re.search(r'^(Description|CUSTOMER|GRAND|PAGE|Total|Invoice|Tax|Bank|IBAN|SWIFT|Payment)', stripped, re.IGNORECASE):
                continue

            # Ищем строки товаров: описание + число + цена (2+ чисел в строке)
            # Формат: "Laptop Dell Latitude 5540 5 850.00 807.50 4250.00"
            parts = stripped.split()
            numbers = [p for p in parts if re.match(r'^\d+[\.,]?\d*$', p)]
            if len(numbers) >= 2:
                # Последнее число - amount, предпоследнее - price, перед ним - qty
                try:
                    amount = float(numbers[-1].replace(',', '.'))
                    unit_price = float(numbers[-2].replace(',', '.'))
                    qty_candidates = [int(float(n.replace(',', '.'))) for n in numbers[:-2] if n.replace(',', '.').replace('.','',1).isdigit()]
                    qty = qty_candidates[-1] if qty_candidates else None
                    # Всё до первого числа — описание
                    first_num_idx = None
                    for i, p in enumerate(parts):
                        if re.match(r'^\d+[\.,]?\d*$', p):
                            first_num_idx = i
                            break
                    desc = ' '.join(parts[:first_num_idx]) if first_num_idx else stripped
                    items.append({"description": desc, "quantity": qty, "price": unit_price})
                except (ValueError, IndexError):
                    pass
            else:
                # Старый формат: строки с qty/quantity/price
                if re.search(r'\b\d+\s*x\s*\d+|qty|quantity|price', stripped, re.IGNORECASE):
                    qty_match = re.search(r'(?:qty|quantity|кол-во)[\s:]*(\d+)', stripped, re.IGNORECASE)
                    qty = int(qty_match.group(1)) if qty_match else None
                    price_match = re.search(r'(?:price|цена)[\s:]*[\$€£]?\s*(\d+[\.,]\d+)', stripped, re.IGNORECASE)
                    price = float(price_match.group(1).replace(',', '.')) if price_match else None
                    if qty or price:
                        items.append({"description": stripped, "quantity": qty, "price": price})

        return items
    
    def _extract_section(self, text: str, start_keywords: list, end_keywords: list) -> str:
        """Извлекает раздел текста между ключевыми словами начала и конца"""
        text_upper = text.upper()
        
        # Ищем позицию начала
        start_pos = -1
        for kw in start_keywords:
            pos = text_upper.find(kw.upper())
            if pos >= 0:
                start_pos = pos
                break
        
        if start_pos == -1:
            return None
        
        # Ищем позицию конца
        end_pos = len(text)
        for kw in end_keywords:
            pos = text_upper.find(kw.upper(), start_pos)
            if pos >= 0 and pos < end_pos:
                end_pos = pos
        
        # Извлекаем и возвращаем раздел
        section = text[start_pos:end_pos]
        # Удаляем первую строку (строка с ключевым словом начала)
        lines = section.split('\n')
        if len(lines) > 1:
            return '\n'.join(lines[1:])
        return None


    def _extract_from_pdf(self, pdf_path: str) -> Tuple[str, Dict[str, Any]]:
        """Извлекает текст из PDF: сначала пробует прямой текст (PyPDF2),
        если текста мало — использует OCR (pdf2image + tesseract).

        Возвращает кортеж (тип_документа, извлеченные_данные).
        """
        # 1. Пробуем извлечь текст напрямую (для цифровых PDF)
        try:
            reader = PdfReader(pdf_path)
            direct_text = ""
            for page in reader.pages:
                direct_text += page.extract_text() + "\n"
            # Если текста достаточно — используем его
            if len(direct_text.strip()) > 50:
                self.raw_text = direct_text
                self.document_type = self._detect_document_type(self.raw_text)
                extracted_data = self._extract_by_type(self.document_type)
                return self.document_type, extracted_data
        except Exception:
            pass  # Fallback to OCR

        # 2. OCR (для сканов и картинок в PDF)
        try:
            poppler_path = "/Users/irina/miniconda3/bin"
            if os.path.isdir(poppler_path):
                pages = convert_from_path(pdf_path, dpi=200, poppler_path=poppler_path)
            else:
                pages = convert_from_path(pdf_path, dpi=200)
        except Exception as e:
            raise RuntimeError(f"Не удалось конвертировать PDF: {e}")

        texts: List[str] = []
        for page in pages:
            rgb = np.array(page.convert('RGB'))
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            processed = self._preprocess_image(bgr)
            page_text = pytesseract.image_to_string(processed, lang='eng+rus')
            texts.append(page_text)

        self.raw_text = "\n".join(texts)
        self.document_type = self._detect_document_type(self.raw_text)
        extracted_data = self._extract_by_type(self.document_type)

        return self.document_type, extracted_data
