"""
pipeline/ — Pinteresto Full Autonomous Pipeline

STEP 1: keyword_agent        → Weekly viral keywords + daily pin slot planning
STEP 2: pin_content_agent    → Keyword se Title + Description + Hashtags banao
STEP 3: prompt_selector      → Keywords ke basis pe Prompts_Master se best prompt nikalo
STEP 4: image_creator        → tools/image_creator.py (existing) — prompt se image banao
STEP 5: product_extractor    → Generated image se purchasable products extract karo
STEP 6: amazon_fetcher       → Products ka Amazon par similar item dhundho + affiliate link
STEP 7: blog_agent           → Image + products + keywords se SEO blog post banao
STEP 8: firebase_publisher   → Blog Firebase par push karo, slug return karo
STEP 9: pinterest_publisher  → Pin upload karo blog URL ke saath
STEP 10: orchestrator        → Upar ke sab steps ko ek run function me chain karo

Integration ke liye GUIDE.md padho.
"""

from pipeline.keyword_agent      import get_todays_keywords, get_weekly_plan, WeeklyKeyword
from pipeline.pin_content_agent  import generate_pin_content
from pipeline.prompt_selector    import select_best_prompt
from pipeline.product_extractor  import extract_products_from_image
from pipeline.amazon_fetcher     import fetch_amazon_products
from pipeline.blog_agent         import generate_blog_post
from pipeline.firebase_publisher import publish_blog_to_firebase
from pipeline.pinterest_publisher import publish_pin
from pipeline.orchestrator       import run_full_pipeline, run_pipeline_for_keyword

__all__ = [
    # Step 1
    "get_todays_keywords", "get_weekly_plan", "WeeklyKeyword",
    # Step 2
    "generate_pin_content",
    # Step 3
    "select_best_prompt",
    # Step 5
    "extract_products_from_image",
    # Step 6
    "fetch_amazon_products",
    # Step 7
    "generate_blog_post",
    # Step 8
    "publish_blog_to_firebase",
    # Step 9
    "publish_pin",
    # Step 10
    "run_full_pipeline", "run_pipeline_for_keyword",
]
