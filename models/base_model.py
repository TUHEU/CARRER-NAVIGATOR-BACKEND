from abc import ABC, abstractmethod
import pymysql
import pymysql.cursors
from config import Config


class DatabaseConnection:
    """Singleton database connection manager"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_connection(self):
        return pymysql.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )


class BaseModel(ABC):
    """Abstract base model - Abstraction & Inheritance"""
    
    db = DatabaseConnection()
    
    def __init__(self):
        self._table = None
        self._primary_key = 'id'
    
    @abstractmethod
    def get_table_name(self) -> str:
        """Each child must define its table name"""
        pass
    
    def find_by_id(self, id: int):
        """Find record by ID - Polymorphism"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {self.get_table_name()} WHERE {self._primary_key} = %s",
                    (id,)
                )
                return cur.fetchone()
    
    def find_all(self, conditions: dict = None, limit: int = 100, offset: int = 0):
        """Find all records with optional conditions"""
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
        """Update record"""
        updates = ', '.join([f"{k} = %s" for k in data.keys()])
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.get_table_name()} SET {updates} WHERE {self._primary_key} = %s",
                    list(data.values()) + [id]
                )
                return cur.rowcount > 0
    
    def delete(self, id: int) -> bool:
        """Delete record"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.get_table_name()} WHERE {self._primary_key} = %s",
                    (id,)
                )
                return cur.rowcount > 0