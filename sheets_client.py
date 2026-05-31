import gspread
from google.oauth2.service_account import Credentials
import re

class SheetsClient:
    def __init__(self, sa_json_path, spreadsheet_url, worksheet_name=None):
        self.sa_json_path = sa_json_path
        self.spreadsheet_url = spreadsheet_url
        self.worksheet_name = worksheet_name
        self.client = None
        self.sheet = None
        self._authenticate()

    def _authenticate(self):
        """
        使用 Service Account JSON 檔案進行 Google Sheets API 認證
        """
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        try:
            credentials = Credentials.from_service_account_file(
                self.sa_json_path, scopes=scopes
            )
            self.client = gspread.authorize(credentials)
            
            # Extract ID from URL or assume it is an ID
            match = re.search(r'/d/([a-zA-Z0-9-_]+)', self.spreadsheet_url)
            sheet_id = match.group(1) if match else self.spreadsheet_url
            spreadsheet = self.client.open_by_key(sheet_id)
            
            if self.worksheet_name:
                self.sheet = spreadsheet.worksheet(self.worksheet_name)
            else:
                self.sheet = spreadsheet.sheet1
        except Exception as e:
            raise Exception(f"Google 試算表連線失敗，請檢查權限與網址: {e}")

    @staticmethod
    def get_worksheet_names(sa_json_path, spreadsheet_url):
        """
        取得試算表中所有的工作表名稱
        """
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        try:
            credentials = Credentials.from_service_account_file(sa_json_path, scopes=scopes)
            client = gspread.authorize(credentials)
            
            match = re.search(r'/d/([a-zA-Z0-9-_]+)', spreadsheet_url)
            sheet_id = match.group(1) if match else spreadsheet_url
            spreadsheet = client.open_by_key(sheet_id)
            
            return [ws.title for ws in spreadsheet.worksheets()]
        except Exception as e:
            raise Exception(f"無法取得工作表清單: {e}")

    def load_sheet_data(self):
        """
        載入所有藥品資料。
        回傳 List of dicts，包含 row_index 方便後續精確寫入。
        """
        all_values = self.sheet.get_all_values()
        if not all_values:
            return []
        
        data = []
        # 從第 2 列開始讀取 (假設第 1 列為標題)
        for idx, row in enumerate(all_values[1:], start=2):
            # Pad row to at least 8 elements (A to H) to avoid IndexError
            row = row + [""] * (8 - len(row))
            
            box, blister, pill = row[3].strip(), row[4].strip(), row[5].strip()
            qty_str = ""
            if box or blister or pill:
                qty_str = f"已盤點(盒:{box} 片:{blister} 顆:{pill})"
            else:
                qty_str = "尚未盤點"
                
            unit_str = f"每盒{row[6]}顆, 每片{row[7]}顆"
            
            row_data = {
                "row_index": idx,
                "代碼": row[0].strip(),
                "名稱": row[1].strip(),
                "儲位": row[2].strip(),
                "盤點狀態": qty_str,
                "包裝單位": unit_str
            }
            
            # 略過完全空白的列
            if any(row_data[k] for k in ["代碼", "名稱", "儲位"]):
                data.append(row_data)
        return data

    def update_drug_quantity(self, row_index, box=None, blister=None, pill=None, unit_box=None, unit_blister=None):
        """
        更新指定列的數量或單位含量。
        box: 數量(盒/罐/束) -> Col 4 (D)
        blister: 數量(片) -> Col 5 (E)
        pill: 數量(顆) -> Col 6 (F)
        unit_box: 單位含量(每盒幾顆) -> Col 7 (G)
        unit_blister: 單位含量(每片幾顆) -> Col 8 (H)
        """
        updates = []
        if box is not None:
            updates.append({'range': f'D{row_index}', 'values': [[box]]})
        if blister is not None:
            updates.append({'range': f'E{row_index}', 'values': [[blister]]})
        if pill is not None:
            updates.append({'range': f'F{row_index}', 'values': [[pill]]})
        if unit_box is not None:
            updates.append({'range': f'G{row_index}', 'values': [[unit_box]]})
        if unit_blister is not None:
            updates.append({'range': f'H{row_index}', 'values': [[unit_blister]]})
            
        if updates:
            self.sheet.batch_update(updates)
            return True
        return False

    def append_new_drug(self, name, box=None, blister=None, pill=None, code=None, location=None, unit_box=None, unit_blister=None):
        """
        在試算表最後方新增一筆未列帳的藥品與數量。
        """
        # 取得下一列的 index 來寫入公式
        next_row_index = len(self.sheet.get_all_values()) + 1
        formula = f"=D{next_row_index}*G{next_row_index} + E{next_row_index}*H{next_row_index} + F{next_row_index}"
        
        new_row = [
            code or "",      # A: 代碼
            name,            # B: 名稱
            location or "",  # C: 儲位
            box or "",       # D: 盒/罐/束
            blister or "",   # E: 片
            pill or "",      # F: 顆
            unit_box or "",  # G: 單位含量(每盒/罐/束幾顆)
            unit_blister or "", # H: 單位含量(每片幾顆)
            formula          # I: 總顆數公式
        ]
        
        self.sheet.append_row(new_row, value_input_option="USER_ENTERED")
        return next_row_index


if __name__ == "__main__":
    # 簡單測試用
    print("Google Sheets 模組已準備好。")
