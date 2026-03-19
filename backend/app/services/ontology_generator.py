"""
本体生成服务
接口1：分析文本内容，生成适合社会模拟的实体和关系类型定义
"""

import json
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient


# 本体生成的系统提示词
ONTOLOGY_SYSTEM_PROMPT = """あなたはプロフェッショナルな知識グラフオントロジー設計の専門家です。あなたの任務は、与えられたテキスト内容とシミュレーション要件を分析し、**ソーシャルメディア世論シミュレーション**に適したエンティティタイプとリレーションタイプを設計することです。

**重要：有効なJSON形式のデータのみを出力してください。それ以外の内容は出力しないでください。**

## コアタスクの背景

私たちは**ソーシャルメディア世論シミュレーションシステム**を構築しています。このシステムでは：
- 各エンティティは、ソーシャルメディア上で発言・交流・情報発信できる「アカウント」または「主体」です
- エンティティ同士は相互に影響し合い、リポスト・コメント・返信を行います
- 世論イベントにおける各方面の反応と情報拡散経路をシミュレーションする必要があります

したがって、**エンティティは現実に存在し、ソーシャルメディア上で発言・交流できる主体でなければなりません**：

**可能なもの**：
- 具体的な個人（公人、当事者、オピニオンリーダー、専門家、一般人）
- 企業・会社（公式アカウントを含む）
- 組織・機関（大学、協会、NGO、労働組合など）
- 政府機関・規制当局
- メディア機関（新聞、テレビ局、個人メディア、ウェブサイト）
- ソーシャルメディアプラットフォーム自体
- 特定グループの代表（同窓会、ファンクラブ、権利擁護団体など）

**不可なもの**：
- 抽象的な概念（「世論」「感情」「トレンド」など）
- テーマ・トピック（「学術的誠実性」「教育改革」など）
- 意見・態度（「支持派」「反対派」など）

## 出力形式

以下の構造を含むJSON形式で出力してください：

```json
{
    "entity_types": [
        {
            "name": "エンティティタイプ名（英語、PascalCase）",
            "description": "簡潔な説明（英語、100文字以内）",
            "attributes": [
                {
                    "name": "属性名（英語、snake_case）",
                    "type": "text",
                    "description": "属性の説明"
                }
            ],
            "examples": ["エンティティ例1", "エンティティ例2"]
        }
    ],
    "edge_types": [
        {
            "name": "リレーションタイプ名（英語、UPPER_SNAKE_CASE）",
            "description": "簡潔な説明（英語、100文字以内）",
            "source_targets": [
                {"source": "ソースエンティティタイプ", "target": "ターゲットエンティティタイプ"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "テキスト内容の簡潔な分析説明（日本語を使用してください）"
}
```

## 設計ガイドライン（非常に重要！）

### 1. エンティティタイプの設計 - 厳守すること

**数量要件：必ず10個のエンティティタイプ**

**階層構造要件（具体タイプとフォールバックタイプの両方を含める必要があります）**：

10個のエンティティタイプには以下の階層を含める必要があります：

A. **フォールバックタイプ（必須、リストの最後の2つに配置）**：
   - `Person`: あらゆる自然人のフォールバックタイプ。より具体的な人物タイプに該当しない場合、このカテゴリに分類します。
   - `Organization`: あらゆる組織・機関のフォールバックタイプ。より具体的な組織タイプに該当しない場合、このカテゴリに分類します。

B. **具体タイプ（8個、テキスト内容に基づいて設計）**：
   - テキストに登場する主要な役割に対して、より具体的なタイプを設計します
   - 例：テキストが学術イベントに関するものなら、`Student`, `Professor`, `University` など
   - 例：テキストがビジネスイベントに関するものなら、`Company`, `CEO`, `Employee` など

**フォールバックタイプが必要な理由**：
- テキストには「小中学校の教師」「通りすがりの人」「あるネットユーザー」など、様々な人物が登場します
- 専用のタイプに一致しない場合、`Person` に分類すべきです
- 同様に、小規模な組織や臨時のグループは `Organization` に分類すべきです

**具体タイプの設計原則**：
- テキストから高頻度で出現する、または重要な役割タイプを識別する
- 各具体タイプには明確な境界を持たせ、重複を避ける
- description でこのタイプとフォールバックタイプの違いを明確に説明する

### 2. リレーションタイプの設計

- 数量：6〜10個
- リレーションはソーシャルメディアでの実際のつながりを反映すべき
- リレーションの source_targets が定義したエンティティタイプをカバーしていることを確認する

### 3. 属性の設計

- 各エンティティタイプに1〜3個の主要属性
- **注意**：属性名に `name`、`uuid`、`group_id`、`created_at`、`summary` は使用不可（システム予約語）
- 推奨：`full_name`, `title`, `role`, `position`, `location`, `description` など

## エンティティタイプ参考

**個人カテゴリ（具体）**：
- Student: 学生
- Professor: 教授・学者
- Journalist: 記者
- Celebrity: 芸能人・インフルエンサー
- Executive: 経営幹部
- Official: 政府関係者
- Lawyer: 弁護士
- Doctor: 医師

**個人カテゴリ（フォールバック）**：
- Person: あらゆる自然人（上記の具体タイプに該当しない場合に使用）

**組織カテゴリ（具体）**：
- University: 大学
- Company: 企業
- GovernmentAgency: 政府機関
- MediaOutlet: メディア機関
- Hospital: 病院
- School: 小中学校
- NGO: 非政府組織

**組織カテゴリ（フォールバック）**：
- Organization: あらゆる組織・機関（上記の具体タイプに該当しない場合に使用）

## リレーションタイプ参考

- WORKS_FOR: 勤務先
- STUDIES_AT: 在学先
- AFFILIATED_WITH: 所属先
- REPRESENTS: 代表する
- REGULATES: 規制する
- REPORTS_ON: 報道する
- COMMENTS_ON: コメントする
- RESPONDS_TO: 返答する
- SUPPORTS: 支持する
- OPPOSES: 反対する
- COLLABORATES_WITH: 協力する
- COMPETES_WITH: 競合する
"""


class OntologyGenerator:
    """
    本体生成器
    分析文本内容，生成实体和关系类型定义
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成本体定义
        
        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模拟需求描述
            additional_context: 额外上下文
            
        Returns:
            本体定义（entity_types, edge_types等）
        """
        # 构建用户消息
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
        
        # 调用LLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )
        
        # 验证和后处理
        result = self._validate_and_process(result)
        
        return result
    
    # 传给 LLM 的文本最大长度（5万字）
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """构建用户消息"""
        
        # 合并文本
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # 如果文本超过5万字，截断（仅影响传给LLM的内容，不影响图谱构建）
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(原文は全{original_length}文字、先頭{self.MAX_TEXT_LENGTH_FOR_LLM}文字をオントロジー分析用に抽出)..."
        
        message = f"""## シミュレーション要件

{simulation_requirement}

## ドキュメント内容

{combined_text}
"""

        if additional_context:
            message += f"""
## 補足説明

{additional_context}
"""

        message += """
上記の内容に基づいて、社会世論シミュレーションに適したエンティティタイプとリレーションタイプを設計してください。

**必ず守るべきルール**：
1. 必ず10個のエンティティタイプを出力すること
2. 最後の2つはフォールバックタイプ：Person（個人フォールバック）と Organization（組織フォールバック）であること
3. 最初の8個はテキスト内容に基づいて設計した具体タイプであること
4. すべてのエンティティタイプは現実に発言できる主体であり、抽象的な概念は不可
5. 属性名に name、uuid、group_id などの予約語は使用不可。full_name、org_name などで代替すること
"""
        
        return message
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """验证和后处理结果"""
        
        # 确保必要字段存在
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # 验证实体类型
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # 确保description不超过100字符
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # 验证关系类型
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # Zep API 限制：最多 10 个自定义实体类型，最多 10 个自定义边类型
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10
        
        # 兜底类型定义
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # 检查是否已有兜底类型
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # 需要添加的兜底类型
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # 如果添加后会超过 10 个，需要移除一些现有类型
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # 计算需要移除多少个
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # 从末尾移除（保留前面更重要的具体类型）
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # 添加兜底类型
            result["entity_types"].extend(fallbacks_to_add)
        
        # 最终确保不超过限制（防御性编程）
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        将本体定义转换为Python代码（类似ontology.py）
        
        Args:
            ontology: 本体定义
            
        Returns:
            Python代码字符串
        """
        code_lines = [
            '"""',
            'カスタムエンティティタイプ定義',
            'MiroFishにより自動生成、社会世論シミュレーション用',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== エンティティタイプ定義 ==============',
            '',
        ]
        
        # 生成实体类型
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== リレーションタイプ定義 ==============')
        code_lines.append('')
        
        # 生成关系类型
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # 转换为PascalCase类名
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # 生成类型字典
        code_lines.append('# ============== タイプ設定 ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # 生成边的source_targets映射
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)

