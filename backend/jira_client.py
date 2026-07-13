import httpx
import asyncio

class JiraClient:
    def __init__(self, url: str, username: str, api_token: str):
        self.base_url = url.rstrip('/')
        self.username = username
        self.api_token = api_token
        self.auth = (username, api_token)
        self.headers = {"Accept": "application/json"}

    async def fetch_users(self) -> list:
        """
        Возвращает список всех реальных пользователей Atlassian Cloud (accountType == 'atlassian').
        """
        results = []
        start_at = 0
        max_results = 100
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                url = f"{self.base_url}/rest/api/3/users/search"
                # Запрашиваем всех пользователей (включая неактивных для контроля)
                params = {
                    "startAt": start_at,
                    "maxResults": max_results
                }
                res = await client.get(url, auth=self.auth, headers=self.headers, params=params)
                if res.status_code != 200:
                    raise Exception(f"Jira API Error: failed to fetch users. Code: {res.status_code}, Body: {res.text}")
                
                data = res.json()
                if not isinstance(data, list):
                    break
                
                # Фильтруем системные записи и внешних JSM-клиентов, оставляем только реальных пользователей
                filtered = [u for u in data if u.get("accountType") == "atlassian"]
                results.extend(filtered)
                
                if len(data) < max_results:
                    break
                start_at += len(data)
                
        return results

    async def fetch_user_groups(self, account_id: str) -> list:
        """
        Возвращает названия групп, в которых состоит пользователь.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                url = f"{self.base_url}/rest/api/3/user/groups"
                res = await client.get(url, auth=self.auth, headers=self.headers, params={"accountId": account_id})
                if res.status_code != 200:
                    return []
                return [g.get("name") for g in res.json() if "name" in g]
        except Exception:
            return []

    async def fetch_projects_and_roles(self) -> dict:
        """
        Обходит проекты и роли, возвращая структуру распределения ролей:
        {
            "users": { "accountId": { "PROJ": ["RoleName"] } },
            "groups": { "GroupName": { "PROJ": ["RoleName"] } }
        }
        """
        user_project_roles = {}
        group_project_roles = {}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 1. Получаем список проектов
                url_projects = f"{self.base_url}/rest/api/3/project"
                res_p = await client.get(url_projects, auth=self.auth, headers=self.headers)
                if res_p.status_code != 200:
                    return {"users": {}, "groups": {}}
                
                projects = res_p.json()
                if not isinstance(projects, list):
                    return {"users": {}, "groups": {}}

                # 2. Обходим роли по каждому проекту в параллельных запросах
                async def process_project(project):
                    p_key = project.get("key")
                    if not p_key:
                        return
                    
                    try:
                        # Получаем список ролей проекта
                        url_roles = f"{self.base_url}/rest/api/3/project/{p_key}/role"
                        res_r = await client.get(url_roles, auth=self.auth, headers=self.headers)
                        if res_r.status_code != 200:
                            return
                        
                        roles_map = res_r.json() # { "RoleName": "https://.../role/10002" }
                        
                        # Обходим участников каждой роли
                        for role_name, role_url in roles_map.items():
                            role_id = role_url.split('/')[-1]
                            
                            url_actors = f"{self.base_url}/rest/api/3/project/{p_key}/role/{role_id}"
                            res_a = await client.get(url_actors, auth=self.auth, headers=self.headers)
                            if res_a.status_code != 200:
                                continue
                            
                            actors_data = res_a.json()
                            actors = actors_data.get("actors", [])
                            
                            for actor in actors:
                                actor_type = actor.get("type")
                                
                                if actor_type == "atlassian-user-role-actor":
                                    user_id = actor.get("actorUser", {}).get("accountId")
                                    if user_id:
                                        if user_id not in user_project_roles:
                                            user_project_roles[user_id] = {}
                                        if p_key not in user_project_roles[user_id]:
                                            user_project_roles[user_id][p_key] = []
                                        if role_name not in user_project_roles[user_id][p_key]:
                                            user_project_roles[user_id][p_key].append(role_name)
                                            
                                elif actor_type == "atlassian-group-role-actor":
                                    g_name = actor.get("actorGroup", {}).get("name")
                                    if g_name:
                                        if g_name not in group_project_roles:
                                            group_project_roles[g_name] = {}
                                        if p_key not in group_project_roles[g_name]:
                                            group_project_roles[g_name][p_key] = []
                                        if role_name not in group_project_roles[g_name][p_key]:
                                            group_project_roles[g_name][p_key].append(role_name)
                    except Exception:
                        pass

                # Выполняем параллельно по всем проектам
                await asyncio.gather(*(process_project(p) for p in projects))

        except Exception as e:
            print(f"JiraClient roles fetch error: {e}")

        return {
            "users": user_project_roles,
            "groups": group_project_roles
        }
