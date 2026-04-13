import re

file_path = '/Users/aditya/temp/vm/submission2/tests/test_integration.py'
with open(file_path, 'r') as f:
    content = f.read()

replacements = [
    (r"'/auth/signup'", r"'/v1/auth/register'"),
    (r"'/auth/signup/verify'", r"'/v1/auth/register/verify'"),
    (r"'/auth/login_step1'", r"'/v1/auth/login'"),
    (r"'/auth/login_step2'", r"'/v1/auth/login/verify'"),
    (r"'/profile/upload_resume'", r"'/v1/users/resumes'")
]

for old_regex, new_val in replacements:
    content = re.sub(old_regex, new_val, content)

with open(file_path, 'w') as f:
    f.write(content)
print("Updated test_integration.py")
