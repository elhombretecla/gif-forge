Name:           gif-forge
Version:        0.1.0
Release:        1%{?dist}
Summary:        Modern Linux screen recorder and GIF/video editor

License:        GPL-3.0-or-later
URL:            https://github.com/elhombretecla/gif-forge
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  pyproject-rpm-macros
BuildRequires:  glib2-devel
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       gstreamer1-plugin-pipewire
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
# ffmpeg lives in RPM Fusion, not in Fedora proper. Users must enable RPM Fusion
# (see docs/PACKAGING.md). COPR builds cannot pull it from the official repos.
Requires:       ffmpeg
Recommends:     gifski

%global appid io.github.elhombretecla.GifForge

%description
GIF Forge records a region, window or screen on Wayland or X11, then lets you
refine the result on a timeline (trim, cut, reorder, retime, crop, undo/redo)
before exporting an optimized GIF, WebM or APNG. It is built in Python with
GTK4 and Libadwaita and uses ffmpeg (and optionally gifski) for encoding.

%prep
%autosetup -n %{name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
# Reuse the shared data installer for desktop/metainfo/gschema/icons.
sh build-aux/flatpak/install-data.sh %{buildroot}%{_prefix}
# Do not ship the compiled schema cache; the glib2 file trigger regenerates it.
rm -f %{buildroot}%{_datadir}/glib-2.0/schemas/gschemas.compiled

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
appstream-util validate-relax --nonet \
    %{buildroot}%{_datadir}/metainfo/%{appid}.metainfo.xml

%files
%license LICENSE
%doc README.md
%{python3_sitelib}/gifforge/
%{python3_sitelib}/gifforge-*.dist-info/
%{_bindir}/gif-forge
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/metainfo/%{appid}.metainfo.xml
%{_datadir}/glib-2.0/schemas/%{appid}.gschema.xml
%{_datadir}/icons/hicolor/*/apps/%{appid}.png

%changelog
* Fri May 29 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com> - 0.1.0-1
- Initial RPM packaging.
