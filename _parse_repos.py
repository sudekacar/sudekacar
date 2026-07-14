import os
import re
import requests

def get_github_stats(username, token):
    headers = {"Authorization": f"token {token}"} if token else {}
    
    # Kullanıcı genel bilgilerini al
    user_url = f"https://api.github.com/users/{username}"
    user_data = requests.get(user_url, headers=headers).json()
    
    followers = user_data.get("followers", 0)
    public_repos = user_data.get("public_repos", 0)
    
    # Repoları tara (Yıldızlar ve Commit'ler için)
    repos_url = f"https://api.github.com/users/{username}/repos?per_page=100"
    repos = requests.get(repos_url, headers=headers).json()
    
    total_stars = 0
    if isinstance(repos, list):
        for repo in repos:
            total_stars += repo.get("stargazers_count", 0)
            
    return followers, public_repos, total_stars

def update_readme():
    username = "sudekacar"
    token = os.getenv("ACCESS_TOKEN")
    
    try:
        followers, repos, stars = get_github_stats(username, token)
    except Exception as e:
        print(f"API hatası: {e}")
        return

    readme_path = "README.md"
    if not os.path.exists(readme_path):
        print("README.md bulunamadı!")
        return
        
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    # README içindeki sayıları regex (düzenli ifadeler) ile güncelle
    # Repos Güncelleme
    content = re.sub(
        r"(★ <b>repos \(Contributed: \d+\)</b>:\s*)\d+", 
        rf"\g<1>{repos}", 
        content
    )
    # Stars Güncelleme
    content = re.sub(
        r"(★ <b>stars:</b>\s*)\d+", 
        rf"\g<1>{stars}", 
        content
    )
    
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("README.md başarıyla güncellendi!")

if __name__ == "__main__":
    update_readme()