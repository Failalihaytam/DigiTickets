#!/usr/bin/env python3
"""
Test script to verify Supabase connection
"""

import os
from dotenv import load_dotenv
from supabase_db import db

def test_connection():
    """Test Supabase connection and basic operations"""
    print("Testing Supabase connection...")
    print("="*40)
    
    try:
        # Test 1: Get all roles
        print("1. Testing roles retrieval...")
        roles = db.get_all_roles()
        print(f"   ✅ Found {len(roles)} roles")
        for role in roles:
            print(f"      - {role['nom']} (ID: {role['id']})")
        
        # Test 2: Get all users
        print("\n2. Testing users retrieval...")
        users = db.get_all_users()
        print(f"   ✅ Found {len(users)} users")
        for user in users[:3]:  # Show first 3 users
            print(f"      - {user['nom_utilisateur']} ({user['role']['nom']})")
        
        # Test 3: Get all statuses
        print("\n3. Testing statuses retrieval...")
        statuses = db.get_all_statuses()
        print(f"   ✅ Found {len(statuses)} statuses")
        for status in statuses:
            print(f"      - {status['nom']} (ID: {status['id']})")
        
        # Test 4: Get all tickets
        print("\n4. Testing tickets retrieval...")
        tickets = db.get_all_tickets()
        print(f"   ✅ Found {len(tickets)} tickets")
        
        # Test 5: Test role by name
        print("\n5. Testing role by name...")
        n1_role_id = db.get_role_by_name('N1')
        if n1_role_id:
            print(f"   ✅ N1 role ID: {n1_role_id}")
        else:
            print("   ❌ N1 role not found")
        
        print("\n" + "="*40)
        print("✅ All tests passed! Supabase connection is working.")
        print("="*40)
        
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        print("Please check your .env file and Supabase configuration.")

if __name__ == "__main__":
    load_dotenv()
    test_connection()
