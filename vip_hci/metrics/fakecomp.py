#! /usr/bin/env python

"""
Module with fake companion injection functions.
"""

from __future__ import division, print_function

__author__ = 'Carlos Alberto Gomez Gonzalez'
__all__ = ['collapse_psf_cube',
           'normalize_psf',
           'cube_inject_companions',
           'cube_copies_with_injections',
           'generate_cube_copies_with_injections',
           'frame_inject_companion']

import numpy as np
from scipy import stats
import photutils
from ..preproc import cube_crop_frames, frame_shift, frame_crop, cube_shift
from ..var import (frame_center, fit_2dgaussian, fit_2dairydisk, fit_2dmoffat,
                   get_circle, get_annulus_segments)
from ..conf.utils_conf import print_precision, Progressbar
from ..conf.mem import check_enough_memory


def cube_inject_companions(array, psf_template, angle_list, flevel, plsc,
                           rad_dists, n_branches=1, theta=0, imlib='opencv',
                           interpolation='lanczos4', full_output=False,
                           verbose=True):
    """ Injects fake companions in branches, at given radial distances.

    Parameters
    ----------
    array : 3d/4d array_like
        Input cube. This is copied before the injections take place, so
        ``array`` is never modified.
    psf_template : array_like
        2d array with the normalized psf template. It should have an odd shape.
        It's recommended to run the function ``normalize_psf`` to get a proper
        PSF template. In the ADI+mSDI case it must be a 3d array.
    angle_list : 1d array_like
        List of parallactic angles, in degrees.
    flevel : float or list
        Factor for controlling the brightness of the fake companions.
    plsc : float
        Value of the plsc in arcsec/px. Only used for printing debug output when
        ``verbose=True``.
    rad_dists : float, list or array 1d
        Vector of radial distances of fake companions in pixels.
    n_branches : int, optional
        Number of azimutal branches.
    theta : float, optional
        Angle in degrees for rotating the position of the first branch that by
        default is located at zero degrees. Theta counts counterclockwise from
        the positive x axis.
    imlib : str, optional
        See the documentation of the ``vip_hci.preproc.frame_shift`` function.
    interpolation : str, optional
        See the documentation of the ``vip_hci.preproc.frame_shift`` function.
    full_output : bool, optional
        Returns the ``x`` and ``y`` coordinates of the injections, additionally
        to the new array.
    verbose : bool, optional
        If True prints out additional information.

    Returns
    -------
    array_out : array_like
        Output array with the injected fake companions.
    positions : list of tuple(y, x)
        Coordinates of the injections in the first frame (and first wavelength
        for 4D cubes). Only returned when ``full_output=True``.

    """
    if array.ndim not in [3, 4]:
        raise ValueError('Array is not a cube, 3d or 4d array')
    if array.ndim == 4 and psf_template.ndim != 3:
        raise ValueError('PSF must be a 3d array')

    positions = []

    # ADI case
    if array.ndim == 3:
        ceny, cenx = frame_center(array[0])
        ceny = int(ceny)
        cenx = int(cenx)

        rad_dists = np.asarray(rad_dists).reshape(-1)  # forces ndim=1

        if not rad_dists[-1] < array[0].shape[0]/2:
            raise ValueError('rad_dists last location is at the border (or '
                             'outside) of the field')
        size_fc = psf_template.shape[0]
        nframes = array.shape[0]
        fc_fr = np.zeros_like(array[0])

        w = int(np.ceil(size_fc/2)) - 1
        starty = ceny - w
        startx = cenx - w

        # fake companion in the center of a zeros frame
        fc_fr[starty:starty+size_fc, startx:startx+size_fc] = psf_template

        if size_fc % 2 == 0 and array.shape[1] % 2 == 1:
            # odd cube, even PSF
            fc_fr = frame_shift(fc_fr, -0.5, -0.5, imlib=imlib,
                                interpolation=interpolation)
        elif size_fc % 2 == 1 and array.shape[1] % 2 == 0:
            fc_fr = frame_shift(fc_fr, 0.5, 0.5, imlib=imlib,
                                interpolation=interpolation)

        array_out = array.copy()

        for branch in range(n_branches):
            ang = (branch * 2 * np.pi / n_branches) + np.deg2rad(theta)

            if verbose:
                print('Branch {}:'.format(branch+1))

            for rad in rad_dists:

                for fr in range(nframes):
                    shift_y = rad * np.sin(ang - np.deg2rad(angle_list[fr]))
                    shift_x = rad * np.cos(ang - np.deg2rad(angle_list[fr]))
                    array_out[fr] += (frame_shift(fc_fr, shift_y, shift_x,
                                                  imlib, interpolation)
                                      * flevel)

                pos_y = rad * np.sin(ang) + ceny
                pos_x = rad * np.cos(ang) + cenx
                rad_arcs = rad * plsc

                positions.append((pos_y, pos_x))

                if verbose:
                    print('\t(X,Y)=({:.2f}, {:.2f}) at {:.2f} arcsec '
                          '({:.2f} pxs)'.format(pos_x, pos_y, rad_arcs, rad))

    # ADI+IFS case
    if array.ndim == 4 and psf_template.ndim == 3:
        ceny, cenx = frame_center(array[0, 0])
        ceny = int(float(ceny))
        cenx = int(float(cenx))
        if isinstance(rad_dists, (int, float)):
            check_coor = rad_dists
            rad_dists = np.array([rad_dists])
        elif isinstance(rad_dists, (list, np.ndarray)):
            check_coor = rad_dists[-1]
            rad_dists = np.array(rad_dists)
        if not check_coor < array[0].shape[1]/2.:
            raise ValueError('rad_dists last location is at the border (or '
                             'outside) of the field')

        sizey = array.shape[2]
        sizex = array.shape[3]
        size_fc = psf_template.shape[2]  # considering square frames
        nframes_wav = array.shape[0]
        nframes_adi = array.shape[1]
        fc_fr = np.zeros((nframes_wav, sizey, sizex), dtype=np.float64)  # -> 3d

        for i in range(nframes_wav):
            w = int(np.floor(size_fc/2.))
            # fake companion in the center of a zeros frame
            if (psf_template[0].shape[1] % 2) == 0:
                fc_fr[i, ceny-w:ceny+w, cenx-w:cenx+w] = psf_template[i]
            else:
                fc_fr[i, ceny-w:ceny+w+1, cenx-w:cenx+w+1] = psf_template[i]

        array_out = array.copy()

        for branch in range(n_branches):
            ang = (branch * 2 * np.pi / n_branches) + np.deg2rad(theta)

            if verbose:
                print('Branch {}:'.format(branch+1))

            for rad in rad_dists:

                for fr in range(nframes_adi):
                    shift_y = rad * np.sin(ang - np.deg2rad(angle_list[fr]))
                    shift_x = rad * np.cos(ang - np.deg2rad(angle_list[fr]))
                    shift = cube_shift(fc_fr, shift_y, shift_x, imlib,
                                       interpolation)

                    if isinstance(flevel, (int, float)):
                        array_out[:, fr] += shift * flevel
                    else:
                        array_out[:, fr] += [shift[i] * flevel[i]
                                             for i in range(len(flevel))]

                pos_y = rad * np.sin(ang) + ceny
                pos_x = rad * np.cos(ang) + cenx
                rad_arcs = rad * plsc

                positions.append((pos_y, pos_x))

                if verbose:
                    print('\t(X,Y)=({:.2f}, {:.2f}) at {:.2f} arcsec '
                          '({:.2f} pxs)'.format(pos_x, pos_y, rad_arcs, rad))

    if full_output:
        return array_out, positions
    else:
        return array_out


def cube_copies_with_injections(array, psf_template, angle_list, plsc,
                                n_copies=100, inrad=8, outrad=12,
                                dist_flux=("uniform", 2, 500),
                                check_mem=True):
    """
    Create multiple copies of ``array`` with different random injections.

    This is a wrapper around ``metrics.cube_inject_companions``, which deals
    with multiple copies of the original data cube and generates random
    parameters.

    Parameters
    ----------
    array : 3d/4d array_like
        Original input cube.
    psf_template : 2d/3d array_like
        Array with the normalized psf template. It should have an odd shape.
        It's recommended to run the function ``normalize_psf`` to get a proper
        PSF template. In the ADI+mSDI case it must be a 3d array.
    angle_list : 1d array_like
        List of parallactic angles, in degrees.
    plsc : float
        Value of the plsc in arcsec/px. Only used for printing debug output when
        ``verbose=True``.
    n_copies : int
        This is the number of 'cube copies' returned.
    inrad,outrad : float
        Inner and outer radius of the injections. The actual injection position
        is chosen randomly.
    dist_flux : tuple('method', *params)
        Tuple describing the flux selection. Method can be a function, the
        ``*params`` are passed to it. Method can also be a string, for a
        pre-defined random function:

            ``("skewnormal", skew, mean, var)``
                uses scipy.stats.skewnorm.rvs
            ``("uniform", low, high)``
                uses np.random.uniform
            ``("normal", loc, scale)``
                uses np.random.normal

    check_mem : bool, optional
        If True, verifies that the system has enough memory to store the result.

    Returns
    -------
    fake_data : list of dict
        List of length ``n_copies``. Each element is a dictionary representing a
        copy of the original ``array``, with fake injections. The dictionary
        keys are:

            ``cube``
                Array shaped like the input ``array``, with the fake injections.
            ``position`` : list of tuples(y,x)
                List containing the positions of the injected companions, as
                (y,x) tuples.
            ``dist`` : float
                The distance of the injected companions, which was passed to
                ``cube_inject_companions``.
            ``theta`` : float, degrees
                The initial angle, as passed to ``cube_inject_companions``.
            ``flux`` : float
                The flux passed to ``cube_inject_companions``.

    """
    # TODO: 'mask' parameter for known companions?

    if check_mem and not check_enough_memory(array.nbytes * n_copies, 1.5,
                                             verbose=False):
        raise RuntimeError("cube_copies_with_injections would require more "
                           "memory than available.")

    fake_data = []

    width = outrad - inrad
    yy, xx = get_annulus_segments(array[0], inrad, width)[0]
    num_patches = yy.shape[0]

    # Defining Fluxes according to chosen distribution
    dist_fkt = dict(skewnormal=stats.skewnorm.rvs,
                    normal=np.random.normal,
                    uniform=np.random.uniform).get(dist_flux[0],
                                                   dist_flux[0])
    fluxes = sorted(dist_fkt(*dist_flux[1:], size=n_copies))

    inds_inj = np.random.randint(0, num_patches, size=n_copies)

    # Injections
    for n in Progressbar(range(n_copies), desc="injecting"):

        injx = xx[inds_inj[n]] - frame_center(array[0])[1]
        injy = yy[inds_inj[n]] - frame_center(array[0])[0]
        dist = np.sqrt(injx**2 + injy**2)
        theta = np.mod(np.arctan2(injy, injx) / np.pi * 180, 360)

        fake_cube, positions = cube_inject_companions(
            array, psf_template, angle_list, plsc=plsc,
            flevel=fluxes[n], theta=theta,
            rad_dists=dist, n_branches=1,  # TODO: multiple injections?
            full_output=True, verbose=False
        )

        fake_data.append(dict(
            positions=positions,
            dist=dist, theta=theta, flux=fluxes[n],
            cube=fake_cube
        ))

    return fake_data


def generate_cube_copies_with_injections(array, psf_template, angle_list, plsc,
                                         n_copies=100, inrad=8, outrad=12,
                                         dist_flux=("uniform", 2, 500)):
    """
    Create multiple copies of ``array`` with different random injections.

    This is a wrapper around ``metrics.cube_inject_companions``, which deals
    with multiple copies of the original data cube and generates random
    parameters.

    Parameters
    ----------
    array : 3d/4d array_like
        Original input cube.
    psf_template : 2d/3d array_like
        Array with the normalized psf template. It should have an odd shape.
        It's recommended to run the function ``normalize_psf`` to get a proper
        PSF template. In the ADI+mSDI case it must be a 3d array.
    angle_list : 1d array_like
        List of parallactic angles, in degrees.
    plsc : float
        Value of the plsc in arcsec/px. Only used for printing debug output when
        ``verbose=True``.
    n_copies : int
        This is the number of 'cube copies' returned.
    inrad,outrad : float
        Inner and outer radius of the injections. The actual injection position
        is chosen randomly.
    dist_flux : tuple('method', *params)
        Tuple describing the flux selection. Method can be a function, the
        ``*params`` are passed to it. Method can also be a string, for a
        pre-defined random function:

            ``("skewnormal", skew, mean, var)``
                uses scipy.stats.skewnorm.rvs
            ``("uniform", low, high)``
                uses np.random.uniform
            ``("normal", loc, scale)``
                uses np.random.normal

    Yields
    ------
    fake_data : dict
        Represents a copy of the original ``array``, with fake injections. The
        dictionary keys are:

            ``cube``
                Array shaped like the input ``array``, with the fake injections.
            ``position`` : list of tuples(y,x)
                List containing the positions of the injected companions, as
                (y,x) tuples.
            ``dist`` : float
                The distance of the injected companions, which was passed to
                ``cube_inject_companions``.
            ``theta`` : float, degrees
                The initial angle, as passed to ``cube_inject_companions``.
            ``flux`` : float
                The flux passed to ``cube_inject_companions``.

    """
    # TODO: 'mask' parameter for known companions?

    width = outrad - inrad
    yy, xx = get_annulus_segments(array[0], inrad, width)[0]
    num_patches = yy.shape[0]

    # Defining Fluxes according to chosen distribution
    dist_fkt = dict(skewnormal=stats.skewnorm.rvs,
                    normal=np.random.normal,
                    uniform=np.random.uniform).get(dist_flux[0],
                                                   dist_flux[0])
    fluxes = sorted(dist_fkt(*dist_flux[1:], size=n_copies))

    inds_inj = np.random.randint(0, num_patches, size=n_copies)

    # Injections
    for n in range(n_copies):  # Progressbar(range(n_copies), desc="injecting"):

        injx = xx[inds_inj[n]] - frame_center(array[0])[1]
        injy = yy[inds_inj[n]] - frame_center(array[0])[0]
        dist = np.sqrt(injx**2 + injy**2)
        theta = np.mod(np.arctan2(injy, injx) / np.pi * 180, 360)

        fake_cube, positions = cube_inject_companions(
            array, psf_template, angle_list, plsc=plsc,
            flevel=fluxes[n], theta=theta,
            rad_dists=dist, n_branches=1,  # TODO: multiple injections?
            full_output=True, verbose=False
        )

        yield dict(
            positions=positions,
            dist=dist, theta=theta, flux=fluxes[n],
            cube=fake_cube
        )


def frame_inject_companion(array, array_fc, pos_y, pos_x, flux,
                           imlib='opencv', interpolation='lanczos4'):
    """ Injects a fake companion in a single frame (it could be a single
     multi-wavelength frame) at given coordinates.
    """
    if not (array.ndim == 2 or array.ndim == 3):
        raise TypeError('Array is not a 2d or 3d array.')
    if array.ndim == 2:
        size_fc = array_fc.shape[0]
        ceny, cenx = frame_center(array)
        ceny = int(ceny)
        cenx = int(cenx)
        fc_fr = np.zeros_like(array)
        w = int(np.floor(size_fc/2.))
        # fake companion in the center of a zeros frame
        fc_fr[ceny-w:ceny+w+1, cenx-w:cenx+w+1] = array_fc
        array_out = array + frame_shift(fc_fr, pos_y-ceny, pos_x-cenx, imlib,
                                        interpolation) * flux

    if array.ndim == 3:
        size_fc = array_fc.shape[1]
        ceny, cenx = frame_center(array[0])
        ceny = int(ceny)
        cenx = int(cenx)
        fc_fr = np.zeros_like(array)
        w = int(np.floor(size_fc/2.))
        # fake companion in the center of a zeros frame
        fc_fr[:, ceny-w:ceny+w+1, cenx-w:cenx+w+1] = array_fc
        array_out = array + cube_shift(fc_fr, pos_y - ceny, pos_x - cenx,
                                       imlib, interpolation) * flux

    return array_out


def collapse_psf_cube(array, size, fwhm=4, verbose=True, collapse='mean'):
    """ Creates a 2d PSF template from a cube of non-saturated off-axis frames
    of the star by taking the mean and normalizing the PSF flux.

    Parameters
    ----------
    array : array_like, 3d
        Input cube.
    size : int
        Size of the squared subimage.
    fwhm: float, optional
        The size of the Full Width Half Maximum in pixel.
    verbose : {True,False}, bool optional
        Whether to print to stdout information about file opening, cropping and
        completion of the psf template.
    collapse : {'mean','median'}, string optional
        Defines the way the frames are collapsed.

    Returns
    -------
    psf_normd : array_like
        Normalized PSF.
    """
    if array.ndim != 3 and array.ndim != 4:
        raise TypeError('Array is not a cube, 3d or 4d array.')

    n = array.shape[0]
    psf = cube_crop_frames(array, size=size, verbose=verbose)
    if collapse == 'mean':
        psf = np.mean(psf, axis=0)
    elif collapse == 'median':
        psf = np.median(psf, axis=0)
    else:
        raise TypeError('Collapse mode not recognized.')

    psf_normd = normalize_psf(psf, size=size, fwhm=fwhm)

    if verbose:
        print("Done scaled PSF template from the average of", n, "frames.")
    return psf_normd


def normalize_psf(array, fwhm='fit', size=None, threshold=None, mask_core=None,
                  model='gauss', imlib='opencv', interpolation='lanczos4',
                  force_odd=True, full_output=False, verbose=True):
    """ Normalizes a PSF (2d or 3d array), to have the flux in a 1xFWHM
    aperture equal to one. It also allows to crop the array and center the PSF
    at the center of the frame(s).

    Parameters
    ----------
    array: array_like
        The PSF, 2d (ADI data) or 3d array (IFS data).
    fwhm: int, float, 1d array or str, optional
        The the Full Width Half Maximum in pixels. It can handle a different
        FWHM value for different wavelengths (IFS data). If set to 'fit' then
        a ``model`` (assuming the PSF is centered in the array) is fitted to
        estimate the FWHM in 2D or 3D PSF arrays.
    size : int or None, optional
        If int it will correspond to the size of the squared subimage to be
        cropped form the psf array.
    threshold : None of float, optional
        Sets to zero small values, trying to leave only the core of the PSF.
    mask_core : None of float, optional
        Sets the radius of a circular aperture for the core of the PSF,
        everything else will be set to zero.
    imlib : str, optional
        See the documentation of the ``vip_hci.preproc.frame_shift`` function.
    interpolation : str, optional
        See the documentation of the ``vip_hci.preproc.frame_shift`` function.
    force_odd : str, optional
        If True the resulting array will have odd size (and the PSF will be
        placed at its center). If False, and the frame size is even, then the
        PSF will be put at the center of an even-sized frame.
    full_output : bool, optional
        If True the flux in a FWHM aperture is returned along with the
        normalized PSF.
    verbose : bool, optional
        If True intermediate results are printed out.

    Returns
    -------
    psf_norm: array_like
        The normalized psf.

    If ``full_output`` is True then the normalized PSF is returned along with
    the flux in a FWHM aperture and the FWHM size (the later is useful when the
    ``fwhm`` is set to 'fit'.
    """
    def psf_norm_2d(array, fwhm, size, threshold, mask_core, full_output,
                    verbose):
        """ 2d case """
        if size is not None:
            if size < array.shape[0]:
                psfs = frame_crop(array, size, force=True, verbose=False)
            else:
                psfs = array.copy()
        else:
            psfs = array.copy()

        # we check if the psf is centered and fix it if needed
        cy, cx = frame_center(psfs, verbose=False)
        xcom, ycom = photutils.centroid_com(psfs)
        if not (np.allclose(cy, ycom, atol=1e-2) or
                np.allclose(cx, xcom, atol=1e-2)):
            # first we find the centroid and put it in the center of the array
            centry, centrx = fit_2d(psfs)
            shiftx, shifty = centrx - cx, centry - cy
            psfs = frame_shift(array, -shifty, -shiftx, imlib=imlib,
                               interpolation=interpolation)
            if size is not None:
                psfs = frame_crop(psfs, size, force=True, verbose=False)

            for _ in range(2):
                centry, centrx = fit_2d(psfs)
                cy, cx = frame_center(psfs, verbose=False)
                shiftx, shifty = centrx - cx, centry - cy
                psfs = frame_shift(psfs, -shifty, -shiftx, imlib=imlib,
                                   interpolation=interpolation)

        # we check whether the flux is normalized and fix it if needed
        fwhm_aper = photutils.CircularAperture((frame_center(psfs)), fwhm/2)
        fwhm_aper_phot = photutils.aperture_photometry(psfs, fwhm_aper,
                                                       method='exact')
        fwhm_flux = np.array(fwhm_aper_phot['aperture_sum'])

        if fwhm_flux > 1.1 or fwhm_flux < 0.9:
            psf_norm_array = psfs / np.array(fwhm_aper_phot['aperture_sum'])
        else:
            psf_norm_array = psfs

        if threshold is not None:
            psf_norm_array[np.where(psf_norm_array < threshold)] = 0

        if mask_core is not None:
            psf_norm_array = get_circle(psf_norm_array, radius=mask_core)

        if verbose:
            print("Flux in 1xFWHM aperture: {:.3f}".format(fwhm_flux[0]))

        if full_output:
            return psf_norm_array, fwhm_flux, fwhm
        else:
            return psf_norm_array
    ############################################################################
    if model == 'gauss':
        fit_2d = fit_2dgaussian
    elif model == 'moff':
        fit_2d = fit_2dmoffat
    elif model == 'airy':
        fit_2d = fit_2dairydisk
    else:
        raise ValueError('`Model` not recognized')

    if array.ndim == 2:
        y, x = array.shape
        if size is not None:
            if force_odd and size % 2 == 0:
                size += 1
                msg = "`Force_odd` is True therefore `size` was set to {}"
                print(msg.format(size))
        else:
            if force_odd and y % 2 == 0:
                size = y - 1
                msg = "`Force_odd` is True and frame size is even, therefore "
                msg += "new frame size was set to {}"
                print(msg.format(size))

        if fwhm == 'fit':
            fit = fit_2d(array, full_output=True)
            if model == 'gauss':
                fwhm = np.mean((fit['fwhm_x'], fit['fwhm_y']))
                if verbose:
                    print("Mean FWHM: {:.3f}".format(fwhm))
            elif model == 'moff' or model == 'airy':
                fwhm = fit.fwhm.at[0]
                if verbose:
                    print("FWHM: {:.3f}".format(fwhm))

        res = psf_norm_2d(array, fwhm, size, threshold, mask_core, full_output,
                          verbose)
        return res

    elif array.ndim == 3:
        n, y, x = array.shape
        if size is not None:
            if force_odd and size % 2 == 0:
                size += 1
                msg = "`Force_odd` is True therefore `size` was set to {}"
                print(msg.format(size))
        else:
            if force_odd and y % 2 == 0:
                size = y - 1
                msg = "`Force_odd` is True and frame size is even, therefore "
                msg += "new frame size was set to {}"
                print(msg.format(size))

        if isinstance(fwhm, (int, float)):
            fwhm = [fwhm]*array.shape[0]
        elif fwhm == 'fit':
            fits_vect = [fit_2d(array[i], full_output=True) for i in range(n)]
            if model == 'gauss':
                fwhmx = [fits_vect[i]['fwhm_x'] for i in range(n)]
                fwhmy = [fits_vect[i]['fwhm_y'] for i in range(n)]
                fwhm_vect = [np.mean((fwhmx[i], fwhmy[i])) for i in range(n)]
                fwhm = np.array(fwhm_vect)
                if verbose:
                    print("Mean FWHM per channel: ")
                    print_precision(fwhm)
            elif model == 'moff' or model == 'airy':
                fwhm_vect = [fits_vect[i]['fwhm'] for i in range(n)]
                fwhm = np.array(fwhm_vect)
                fwhm = fwhm.flatten()
                if verbose:
                    print("FWHM per channel:")
                    print_precision(fwhm)

        array_out = []
        fwhm_flux = np.zeros(n)

        for fr in range(array.shape[0]):
            restemp = psf_norm_2d(array[fr], fwhm[fr], size, threshold,
                                  mask_core, True, False)
            array_out.append(restemp[0])
            fwhm_flux[fr] = restemp[1]

        array_out = np.array(array_out)
        if verbose:
            print("Flux in 1xFWHM aperture: ")
            print_precision(fwhm_flux)
        if full_output:
            return array_out, fwhm_flux, fwhm
        else:
            return array_out