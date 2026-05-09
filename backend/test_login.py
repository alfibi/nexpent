from main import verify_password
print("testing argon2...")
print(verify_password("mudi123", "$argon2id$v=19$m=65536,t=3,p=4$l7JW6r2XkjIGoHROyZnzfg$o7DF6kC6Kd5dN1ORz1+xjuxCPYlm4RWTGcZ35ikUPXs", "argon2"))
