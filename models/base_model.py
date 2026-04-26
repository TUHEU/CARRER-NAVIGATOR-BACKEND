"""Base Model Module - Database Connection and Abstract Base Model"""
import pymysql
import pymysql.cursors
from config import Config


class DatabaseManager:
    """Database connection manager - Singleton pattern"""
    
    _config = {
        'host': Config.DB_HOST,
        'port': Config.DB_PORT,
        'user': Config.DB_USER,
        'password': Config.DB_PASSWORD,
        'database': Config.DB_NAME,
        'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.DictCursor,
        'autocommit': True
    }
    
    @classmethod
    def get_connection(cls):
        """Get a new database connection"""
        try:
            return pymysql.connect(**cls._config)
        except Exception as e:
            print(f"Database connection error: {e}")
            raise
    
    @classmethod
    def test(cls) -> bool:
        """Test database connection"""
        try:
            conn = cls.get_connection()
            conn.close()
            return True
        except Exception as e:
            print(f"Database test failed: {e}")
            return False


class BaseModel:
    """Abstract base model - All models inherit from this"""
    
    db = DatabaseManager()
    
    def __init__(self):
        self._table = None
        self._primary_key = 'id'
    
    def get_table_name(self) -> str:
        """Child classes must override this"""
        raise NotImplementedError("Child class must implement get_table_name()")
    
    def find_by_id(self, id: int):
        """Find record by ID"""
        if not self.get_table_name():
            return None
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {self.get_table_name()} WHERE {self._primary_key} = %s",
                    (id,)
                )
                return cur.fetchone()
    
    def find_all(self, conditions: dict = None, limit: int = 100, offset: int = 0):
        """Find all records with optional conditions"""
        if not self.get_table_name():
            return []
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                query = f"SELECT * FROM {self.get_table_name()}"
                params = []
                
                if conditions:
                    where_clause = " AND ".join([f"{k} = %s" for k in conditions.keys()])
                    query += f" WHERE {where_clause}"
                    params.extend(conditions.values())
                
                query += f" LIMIT %s OFFSET %s"
                params.extend([limit, offset])
                
                cur.execute(query, params)
                return cur.fetchall()
    
    def create(self, data: dict) -> int:
        """Create new record"""
        if not self.get_table_name() or not data:
            return 0
        
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self.get_table_name()} ({columns}) VALUES ({placeholders})",
                    list(data.values())
                )
                return cur.lastrowid
    
    def update(self, id: int, data: dict) -> bool:
        """Update record by ID"""
        if not self.get_table_name() or not data:
            return False
        
        updates = ', '.join([f"{k} = %s" for k in data.keys()])
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.get_table_name()} SET {updates} WHERE {self._primary_key} = %s",
                    list(data.values()) + [id]
                )
                return cur.rowcount > 0
    
    def delete(self, id: int) -> bool:
        """Delete record by ID"""
        if not self.get_table_name():
            return False
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.get_table_name()} WHERE {self._primary_key} = %s",
                    (id,)
                )
                return cur.rowcount > 0