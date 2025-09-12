#!/usr/bin/env python3
"""
Supabase Database Helper Module
Provides easy-to-use functions for database operations
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SupabaseDB:
    def __init__(self):
        self.supabase_url = os.environ.get("SUPABASE_URL")
        # Prefer service role key if available; fallback to explicit key, then anon
        self.supabase_key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY")
            or os.environ.get("SUPABASE_ANON_KEY")
        )
        # Request timeout (seconds)
        try:
            self.request_timeout = float(os.environ.get("SUPABASE_REQUEST_TIMEOUT", "20"))
        except ValueError:
            self.request_timeout = 20.0
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and a Supabase key must be set (SERVICE_ROLE/KEY/ANON)")
        
        # Remove trailing slash from URL
        self.supabase_url = self.supabase_url.rstrip('/')
        
    def _make_request(self, method, endpoint, data=None, params=None):
        """Make a request to Supabase REST API"""
        url = f"{self.supabase_url}/rest/v1/{endpoint}"
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=self.request_timeout)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=self.request_timeout)
            elif method.upper() == "PATCH":
                response = requests.patch(url, headers=headers, json=data, timeout=self.request_timeout)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, timeout=self.request_timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json() if response.content else []
            
        except requests.exceptions.RequestException as e:
            print(f"Supabase API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    print(f"Status: {e.response.status_code}")
                    print(f"Response content: {e.response.text}")
                except Exception:
                    pass
            raise
    
    # User operations
    def get_user_by_credentials(self, username, password):
        """Get user by username and password"""
        try:
            result = self._make_request("GET", f"utilisateur?nom_utilisateur=eq.{username}&mot_de_passe=eq.{password}&select=id,nom,role_id,role(nom)")
            if result:
                user = result[0]
                return (user['id'], user['nom'], user['role']['nom'])
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None
    
    def get_user_by_id(self, user_id):
        """Get user by ID"""
        try:
            result = self._make_request("GET", f"utilisateur?id=eq.{user_id}&select=id,nom,role_id,role(nom)")
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting user by ID: {e}")
            return None
    
    def get_all_users(self):
        """Get all users with role information"""
        try:
            result = self._make_request("GET", "utilisateur?select=id,nom_utilisateur,email,prenom,nom,role_id,role(nom)")
            return result
        except Exception as e:
            print(f"Error getting all users: {e}")
            return []
    
    def create_user(self, user_data):
        """Create a new user"""
        try:
            result = self._make_request("POST", "utilisateur", data=user_data)
            return result[0] if result else None
        except Exception as e:
            print(f"Error creating user: {e}")
            return None
    
    def update_user(self, user_id, user_data):
        """Update a user"""
        try:
            result = self._make_request("PATCH", f"utilisateur?id=eq.{user_id}", data=user_data)
            return result[0] if result else None
        except Exception as e:
            print(f"Error updating user: {e}")
            return None
    
    def delete_user(self, user_id):
        """Delete a user"""
        try:
            self._make_request("DELETE", f"utilisateur?id=eq.{user_id}")
            return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False
    
    # Role operations
    def get_role_by_name(self, role_name):
        """Get role by name"""
        try:
            result = self._make_request("GET", f"role?nom=eq.{role_name}&select=id")
            return result[0]['id'] if result else None
        except Exception as e:
            print(f"Error getting role by name: {e}")
            return None
    
    def get_all_roles(self):
        """Get all roles"""
        try:
            result = self._make_request("GET", "role?select=id,nom,description")
            return result
        except Exception as e:
            print(f"Error getting all roles: {e}")
            return []
    
    def get_role_by_id(self, role_id):
        """Get role by ID"""
        try:
            result = self._make_request("GET", f"role?id=eq.{role_id}&select=id,nom,description")
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting role by ID: {e}")
            return None
    
    # Ticket operations
    def get_user_tickets(self, user_id):
        """Get tickets for a specific user"""
        try:
            result = self._make_request("GET", f"ticket?idutilisateur=eq.{user_id}&select=id,titre,description,date_creation,statut_id,statut(nom)&order=date_creation.desc")
            return result
        except Exception as e:
            print(f"Error getting user tickets: {e}")
            return []
    
    def get_all_tickets(self):
        """Get all tickets with user and status information"""
        try:
            result = self._make_request("GET", "ticket?select=id,titre,description,date_creation,statut_id,statut(nom),idutilisateur,utilisateur(nom_utilisateur,prenom,nom)&order=date_creation.desc")
            return result
        except Exception as e:
            print(f"Error getting all tickets: {e}")
            return []
    
    def get_tickets_by_role(self, role_id):
        """Get tickets assigned to a specific role"""
        try:
            result = self._make_request("GET", f"ticket?assigned_role_id=eq.{role_id}&select=id,titre,description,date_creation,statut_id,statut(nom),idutilisateur,utilisateur(nom_utilisateur),required_habilitation_id,assigned_role_id&order=date_creation.desc")
            return result
        except Exception as e:
            print(f"Error getting tickets by role: {e}")
            return []
    
    def create_ticket(self, ticket_data):
        """Create a new ticket"""
        try:
            result = self._make_request("POST", "ticket", data=ticket_data)
            return result[0] if result else None
        except Exception as e:
            print(f"Error creating ticket: {e}")
            return None
    
    def update_ticket(self, ticket_id, ticket_data):
        """Update a ticket"""
        try:
            result = self._make_request("PATCH", f"ticket?id=eq.{ticket_id}", data=ticket_data)
            return result[0] if result else None
        except Exception as e:
            print(f"Error updating ticket: {e}")
            return None
    
    def delete_ticket(self, ticket_id):
        """Delete a ticket"""
        try:
            self._make_request("DELETE", f"ticket?id=eq.{ticket_id}")
            return True
        except Exception as e:
            print(f"Error deleting ticket: {e}")
            return False
    
    def get_ticket_by_id(self, ticket_id):
        """Get ticket by ID with all related data"""
        try:
            result = self._make_request("GET", f"ticket?id=eq.{ticket_id}&select=id,titre,description,date_creation,date_mise_a_jour,date_cloture,statut_id,statut(nom),priorite_id,priorite(nom),categorie_id,categorie(nom),type_id,type(nom),idutilisateur,utilisateur(nom_utilisateur,prenom,nom),assigned_role_id,required_habilitation_id,resolution_due_at,resolution_attempts")
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting ticket by ID: {e}")
            return None
    
    # Status operations
    def get_all_statuses(self):
        """Get all statuses"""
        try:
            result = self._make_request("GET", "statut?select=id,nom")
            return result
        except Exception as e:
            print(f"Error getting all statuses: {e}")
            return []
    
    def get_status_by_name(self, status_name):
        """Get status by name"""
        try:
            result = self._make_request("GET", f"statut?nom=eq.{status_name}&select=id")
            return result[0]['id'] if result else None
        except Exception as e:
            print(f"Error getting status by name: {e}")
            return None
    
    # Category operations
    def get_all_categories(self):
        """Get all categories"""
        try:
            result = self._make_request("GET", "categorie?select=id,nom")
            return result
        except Exception as e:
            print(f"Error getting all categories: {e}")
            return []
    
    # Type operations
    def get_all_types(self):
        """Get all types"""
        try:
            result = self._make_request("GET", "type?select=id,nom")
            return result
        except Exception as e:
            print(f"Error getting all types: {e}")
            return []
    
    # Habilitation operations
    def get_all_habilitations(self):
        """Get all habilitations"""
        try:
            result = self._make_request("GET", "habilitation?select=id,nom,categorie&order=categorie,nom")
            return result
        except Exception as e:
            print(f"Error getting all habilitations: {e}")
            return []
    
    def get_role_habilitations(self, role_id):
        """Get habilitations for a specific role"""
        try:
            result = self._make_request("GET", f"role_habilitation?role_id=eq.{role_id}&select=habilitation_id,habilitation(id,nom,categorie)")
            return [item['habilitation'] for item in result]
        except Exception as e:
            print(f"Error getting role habilitations: {e}")
            return []
    
    def check_role_has_habilitation(self, role_id, habilitation_id):
        """Check if a role has a specific habilitation"""
        try:
            result = self._make_request("GET", f"role_habilitation?role_id=eq.{role_id}&habilitation_id=eq.{habilitation_id}")
            return len(result) > 0
        except Exception as e:
            print(f"Error checking role habilitation: {e}")
            return False
    
    # File operations
    def create_file(self, file_data):
        """Create a file record"""
        try:
            result = self._make_request("POST", "fichier", data=file_data)
            return result[0] if result else None
        except Exception as e:
            print(f"Error creating file: {e}")
            return None
    
    def get_file_by_id(self, file_id):
        """Get file by ID"""
        try:
            result = self._make_request("GET", f"fichier?id=eq.{file_id}&select=id,fichier,ticket_id")
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting file by ID: {e}")
            return None
    
    # Utility functions
    def get_user_count(self, user_id):
        """Get count of tickets for a user"""
        try:
            result = self._make_request("GET", f"ticket?idutilisateur=eq.{user_id}&select=id")
            return len(result)
        except Exception as e:
            print(f"Error getting user ticket count: {e}")
            return 0
    
    def get_tickets_due_for_resolution(self):
        """Get tickets that are due for resolution"""
        try:
            # Get the status ID for 'Incident en cours de résolution'
            in_progress_id = self.get_status_by_name('Incident en cours de résolution')
            if not in_progress_id:
                return []
            
            now = datetime.now().isoformat()
            result = self._make_request("GET", f"ticket?statut_id=eq.{in_progress_id}&resolution_due_at=not.is.null&resolution_due_at=lte.{now}&select=id")
            return result
        except Exception as e:
            print(f"Error getting tickets due for resolution: {e}")
            return []
    
    def update_ticket_status(self, ticket_id, status_id, additional_data=None):
        """Update ticket status and optionally other fields"""
        try:
            data = {"statut_id": status_id}
            if additional_data:
                data.update(additional_data)
            
            result = self._make_request("PATCH", f"ticket?id=eq.{ticket_id}", data=data)
            return result[0] if result else None
        except Exception as e:
            print(f"Error updating ticket status: {e}")
            return None

# Global database instance
db = SupabaseDB()
