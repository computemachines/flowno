.PHONY: deb clean build 

PACKAGE_ROOT = ./package-root

# SYSTEMD_DIRECTORY = $(PACKAGE_ROOT)/usr/lib/systemd/system
# CONFIG_DIRECTORY = $(PACKAGE_ROOT)/etc/project_api
NGINX_CONFIG = $(PACKAGE_ROOT)/etc/nginx/conf.d
# LIB_DIRECTORY = $(PACKAGE_ROOT)/usr/lib/project-frontend
STATIC_WWW = $(PACKAGE_ROOT)/var/www/flowno-docs

clean:
	rm -r dist $(PACKAGE_ROOT)

build-docs:
	# Generate API documentation
	cd docs && make html

deb:
	mkdir -pv $(PACKAGE_ROOT)/DEBIAN
	cp -rv DEBIAN $(PACKAGE_ROOT)
	# chmod +x $(PACKAGE_ROOT)/DEBIAN/postinst $(PACKAGE_ROOT)/DEBIAN/prerm

	# mkdir -pv $(SYSTEMD_DIRECTORY)
	# cp -v systemd/* $(SYSTEMD_DIRECTORY)

	# mkdir -pv $(CONFIG_DIRECTORY)
	# cp -v $(wildcard config/project_*.conf) $(CONFIG_DIRECTORY)

	mkdir -pv $(NGINX_CONFIG)
	cp -v $(wildcard config/pkg_*.conf) $(NGINX_CONFIG)

	# mkdir -pv $(LIB_DIRECTORY)
	# cp -vr $(wildcard dist/*) $(LIB_DIRECTORY)
	
	mkdir -pv $(STATIC_WWW)
	cp -vr docs/build/html/* $(STATIC_WWW)

	mkdir -pv dist/
	dpkg-deb --build $(PACKAGE_ROOT)/ dist/
