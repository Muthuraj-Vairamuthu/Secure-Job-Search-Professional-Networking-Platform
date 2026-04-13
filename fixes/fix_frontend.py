import os
import glob
import re

html_files = glob.glob('/Users/aditya/temp/vm/submission2/frontend/public/*.html')

replacements = [
    (r"'/api/auth/signup'", r"'/api/v1/auth/register'"),
    (r"'/api/auth/signup/verify'", r"'/api/v1/auth/register/verify'"),
    (r"'/api/auth/login_step1'", r"'/api/v1/auth/login'"),
    (r"'/api/auth/login_step2'", r"'/api/v1/auth/login/verify'"),
    (r"'/api/auth/logout'", r"'/api/v1/auth/logout'"),

    (r"'/api/profile/me'", r"'/api/v1/users/me'"),
    # Convert POST /api/profile/update to PUT /api/v1/users/me
    (r"fetch\('/api/profile/update', \{[\s\S]*?method:\s*'POST'", r"fetch('/api/v1/users/me', {\nmethod: 'PUT'"),
    
    (r"'/api/profile/change_password'", r"'/api/v1/users/me/password'"),
    # Same here, it was POST, mapped to PUT in users.py
    (r"fetch\('/api/profile/change_password', \{[\s\S]*?method:\s*'POST'", r"fetch('/api/v1/users/me/password', {\nmethod: 'PUT'"),
    
    (r"'/api/profile/upload_resume'", r"'/api/v1/users/resumes'"),
    (r"'/api/profile/resumes'", r"'/api/v1/users/resumes'"),
    (r"'/api/profile/download_resume/(.*?)'", r"'/api/v1/users/resumes/\1/download'"),
    (r"'/api/profile/delete_resume/(.*?)'", r"'/api/v1/users/resumes/\1'"),

    (r"'/api/companies/mine'", r"'/api/v1/companies/me'"),
    (r"'/api/companies", r"'/api/v1/companies"),
    
    (r"'/api/jobs", r"'/api/v1/jobs"),
    
    (r"'/api/applications/me'", r"'/api/v1/applications/me'"),
    (r"'/api/applications/job", r"'/api/v1/applications/job"),
    (r"'/api/applications/(\${.*?})/status'", r"'/api/v1/applications/\1/status'"),
    (r"'/api/applications", r"'/api/v1/applications"),

    (r"'/api/messages/keys/publish'", r"'/api/v1/messages/keys'"),
    (r"'/api/messages/keys/", r"'/api/v1/messages/keys/"),
    (r"'/api/messages/conversations", r"'/api/v1/messages/conversations"),
    (r"'/api/messages/users", r"'/api/v1/messages/users"),

    (r"'/api/admin/dashboard'", r"'/api/v1/admin/dashboard'")
]

for file_path in html_files:
    with open(file_path, 'r') as f:
        content = f.read()
    
    new_content = content
    for old_regex, new_val in replacements:
        new_content = re.sub(old_regex, new_val, new_content)
    
    # special fix for dynamic routes like `/api/profile/download_resume/${resume.resume_id}` 
    new_content = re.sub(r"'/api/profile/download_resume/(\$.*?)'", r"'/api/v1/users/resumes/\1/download'", new_content)
    new_content = re.sub(r"'/api/profile/delete_resume/(\$.*?)'", r"'/api/v1/users/resumes/\1'", new_content)
    # Special fix to use PUT for password
    new_content = re.sub(r"fetch\('/api/v1/users/me/password', {\s*method: 'POST'", r"fetch('/api/v1/users/me/password', { method: 'PUT'", new_content)
    
    if content != new_content:
        with open(file_path, 'w') as f:
            f.write(new_content)
        print(f"Updated {file_path}")

print("Done.")
