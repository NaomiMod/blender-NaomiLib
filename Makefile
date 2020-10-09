ADDON_DIR=./src
ZIP_NAME="NaomiLib-Blender_07.zip"

addon:
	mkdir -p ${ADDON_DIR}/addon/io_scene_nl
	cp ${ADDON_DIR}/*.py ${ADDON_DIR}/addon/io_scene_nl/
	cd ${ADDON_DIR}/addon/ && zip -r ${ZIP_NAME} io_scene_nl/
	mv ${ADDON_DIR}/addon/${ZIP_NAME} .
	rm -rf ${ADDON_DIR}/addon
clean:
	rm -rf ${ADDON_DIR}/addon
