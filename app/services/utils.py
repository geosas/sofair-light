from PIL import Image, ExifTags
import re


def validate_email(email):
    regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(regex, email) is not None


def allowed_file(filename, allowed):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def resize_image(input_path, output_path, new_width, height_max):
    with Image.open(input_path) as img:
        # Correct the image orientation
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif is not None:
                orientation_value = exif.get(orientation)
                if orientation_value is not None:
                    if orientation_value == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation_value == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation_value == 8:
                        img = img.rotate(90, expand=True)
        except Exception as e:
            print(f"Error while reading EXIF metadata: {e}")

        width, height = img.size
        if width > new_width or height > height_max:
            aspect_ratio = width / height

            if width > new_width:
                width = new_width
                height = int(width / aspect_ratio)

            if height > height_max:
                height = height_max
                width = int(height * aspect_ratio)

            img_resized = img.resize((width, height))
            img_resized.save(output_path)
        else:
            img.save(output_path)


def error_to_dict(e):
    errors = []
    for error in e.errors():
        errors.append({
            "field": error["loc"][0],
            "message": error["msg"]
        })
    return {
        "msg": "Validation failed",
        "errors": errors
    }
