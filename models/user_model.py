from abc import ABC
from models.base_model import BaseModel
import pymysql


class UserModel(BaseModel):
    """User model - Inheritance from BaseModel"""
    
    def get_table_name(self) -> str:
        return 'users'
    
    def find_by_email(self, email: str):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE email = %s",
                    (email.lower(),)
                )
                return cur.fetchone()
    
    def get_full_profile(self, user_id: int):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Get user + job seeker profile
                cur.execute("""
                    SELECT u.*, 
                           js.headline as seeker_headline, js.bio as seeker_bio,
                           js.phone, js.location, js.years_of_experience,
                           js.current_job_title, js.desired_job_title,
                           js.availability, js.skills, js.resume_url,
                           js.linkedin_url, js.github_url, js.portfolio_url
                    FROM users u
                    LEFT JOIN job_seekers js ON js.user_id = u.id
                    WHERE u.id = %s
                """, (user_id,))
                user = cur.fetchone()
                
                if not user:
                    return None
                
                # Get education
                cur.execute(
                    "SELECT * FROM education WHERE user_id = %s ORDER BY start_year DESC",
                    (user_id,)
                )
                user['education'] = cur.fetchall()
                
                # Get work experience
                cur.execute(
                    "SELECT * FROM work_experience WHERE user_id = %s ORDER BY start_date DESC",
                    (user_id,)
                )
                work = cur.fetchall()
                for w in work:
                    if w.get('start_date'):
                        w['start_date'] = str(w['start_date'])
                    if w.get('end_date'):
                        w['end_date'] = str(w['end_date'])
                user['work_experience'] = work
                
                # Get mentor profile if applicable
                if user.get('role') == 'mentor':
                    cur.execute(
                        "SELECT * FROM mentor_profiles WHERE user_id = %s",
                        (user_id,)
                    )
                    user['mentor_profile'] = cur.fetchone()
                
                # Get unread notifications count
                cur.execute(
                    "SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = FALSE",
                    (user_id,)
                )
                user['unread_notifications'] = cur.fetchone()['count']
                
                # Ensure profile_picture_url field exists
                if user.get('profile_picture_url') is None:
                    user['profile_picture_url'] = None
                
                return user
    
    def delete_account(self, user_id: int) -> bool:
        """Soft delete or hard delete account"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Soft delete - set inactive
                cur.execute(
                    "UPDATE users SET is_active = 0, email = CONCAT(email, '.deleted_', UNIX_TIMESTAMP()) WHERE id = %s",
                    (user_id,)
                )
                return cur.rowcount > 0


class JobSeekerModel(BaseModel):
    """Job seeker model - Inheritance"""
    
    def get_table_name(self) -> str:
        return 'job_seekers'
    
    def create_or_update(self, user_id: int, data: dict):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if exists
                cur.execute("SELECT user_id FROM job_seekers WHERE user_id = %s", (user_id,))
                exists = cur.fetchone()
                
                if exists:
                    updates = ', '.join([f"{k} = %s" for k in data.keys()])
                    cur.execute(
                        f"UPDATE job_seekers SET {updates} WHERE user_id = %s",
                        list(data.values()) + [user_id]
                    )
                else:
                    columns = ', '.join(['user_id'] + list(data.keys()))
                    placeholders = ', '.join(['%s'] * (len(data) + 1))
                    cur.execute(
                        f"INSERT INTO job_seekers ({columns}) VALUES ({placeholders})",
                        [user_id] + list(data.values())
                    )
                return True


class MentorModel(BaseModel):
    """Mentor model - Inheritance"""
    
    def get_table_name(self) -> str:
        return 'mentor_profiles'
    
    def create_or_update(self, user_id: int, data: dict):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM mentor_profiles WHERE user_id = %s", (user_id,))
                exists = cur.fetchone()
                
                if exists:
                    updates = ', '.join([f"{k} = %s" for k in data.keys()])
                    cur.execute(
                        f"UPDATE mentor_profiles SET {updates} WHERE user_id = %s",
                        list(data.values()) + [user_id]
                    )
                else:
                    columns = ', '.join(['user_id'] + list(data.keys()))
                    placeholders = ', '.join(['%s'] * (len(data) + 1))
                    cur.execute(
                        f"INSERT INTO mentor_profiles ({columns}) VALUES ({placeholders})",
                        [user_id] + list(data.values())
                    )
                return True
    
    def list_mentors(self, expertise: str = None, page: int = 1, per_page: int = 20):
        offset = (page - 1) * per_page
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                base_query = """
                    SELECT u.id, u.full_name, u.profile_picture_url,
                           mp.headline, mp.current_job_title, mp.current_company,
                           mp.expertise_areas, mp.session_price, mp.currency,
                           mp.rating, mp.total_sessions, mp.is_accepting_mentees
                    FROM mentor_profiles mp
                    JOIN users u ON u.id = mp.user_id
                    WHERE u.is_active = 1 AND mp.is_accepting_mentees = 1
                """
                params = []
                
                if expertise:
                    base_query += " AND JSON_SEARCH(mp.expertise_areas, 'one', %s) IS NOT NULL"
                    params.append(expertise)
                
                base_query += " ORDER BY mp.rating DESC LIMIT %s OFFSET %s"
                params.extend([per_page, offset])
                
                cur.execute(base_query, params)
                mentors = cur.fetchall()
                
                # Parse expertise_areas JSON
                for m in mentors:
                    if m.get('expertise_areas') and isinstance(m['expertise_areas'], str):
                        import json
                        try:
                            m['expertise_areas'] = json.loads(m['expertise_areas'])
                        except:
                            m['expertise_areas'] = []
                
                return mentors