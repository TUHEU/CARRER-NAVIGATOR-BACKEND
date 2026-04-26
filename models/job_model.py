from models.base_model import BaseModel
from datetime import datetime


class JobListingModel(BaseModel):
    """Job listing model - Inheritance"""
    
    def get_table_name(self) -> str:
        return 'job_listings'
    
    def create_job(self, data: dict) -> int:
        """Create a new job listing (admin only)"""
        return self.create(data)
    
    def update_job(self, job_id: int, data: dict) -> bool:
        """Update job listing"""
        return self.update(job_id, data)
    
    def delete_job(self, job_id: int) -> bool:
        """Soft delete job listing"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_listings SET is_active = 0 WHERE id = %s",
                    (job_id,)
                )
                return cur.rowcount > 0
    
    def get_active_jobs(self, filters: dict = None, page: int = 1, per_page: int = 20):
        offset = (page - 1) * per_page
        query = """
            SELECT j.*, u.full_name as posted_by_name
            FROM job_listings j
            JOIN users u ON u.id = j.posted_by
            WHERE j.is_active = 1 AND (j.expires_at IS NULL OR j.expires_at > NOW())
        """
        params = []
        
        if filters:
            if filters.get('location'):
                query += " AND j.location LIKE %s"
                params.append(f"%{filters['location']}%")
            if filters.get('employment_type'):
                query += " AND j.employment_type = %s"
                params.append(filters['employment_type'])
            if filters.get('search'):
                query += " AND (j.title LIKE %s OR j.company LIKE %s OR j.description LIKE %s)"
                params.extend([f"%{filters['search']}%"] * 3)
        
        query += " ORDER BY j.created_at DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                jobs = cur.fetchall()
                
                # Format dates
                for job in jobs:
                    if job.get('created_at'):
                        job['created_at'] = str(job['created_at'])
                
                return jobs
    
    def apply_for_job(self, job_id: int, user_id: int, cover_letter: str = None, resume_url: str = None) -> bool:
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if already applied
                cur.execute(
                    "SELECT id FROM job_applications WHERE job_id = %s AND user_id = %s",
                    (job_id, user_id)
                )
                if cur.fetchone():
                    return False
                
                cur.execute(
                    """INSERT INTO job_applications (job_id, user_id, cover_letter, resume_url) 
                       VALUES (%s, %s, %s, %s)""",
                    (job_id, user_id, cover_letter, resume_url)
                )
                return True
    
    def get_user_applications(self, user_id: int):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.*, j.title, j.company, j.location, j.employment_type
                    FROM job_applications a
                    JOIN job_listings j ON j.id = a.job_id
                    WHERE a.user_id = %s
                    ORDER BY a.applied_at DESC
                """, (user_id,))
                apps = cur.fetchall()
                for app in apps:
                    if app.get('applied_at'):
                        app['applied_at'] = str(app['applied_at'])
                return apps