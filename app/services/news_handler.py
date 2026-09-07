from datetime import datetime
from flask_jwt_extended import current_user
import json
import os

from app.config import Config


def generate_article(titre, resume, corps, image_path, image_path_preview):
    article_id = f"article_{len(Config.APP_NEWS)+1}"

    Config.APP_NEWS[article_id] = {
        "titre": titre,
        "auteur": current_user.username,
        "date": datetime.now().strftime("%Y-%m-%d"),  # ISO 8601, consistent with metadata dates
        "resume": resume,
        "corps article": corps,
        "image_preview": image_path_preview,
        "image": image_path
    }

    file_path = os.path.join(Config.BASEDIR,
                             'data', 'news', 'news.json')

    # be careful not to lose everything.... -> sqlite ?
    with open(file_path, 'w', encoding="utf-8") as json_file:
        json.dump(Config.APP_NEWS, json_file, indent=4)
    return article_id
